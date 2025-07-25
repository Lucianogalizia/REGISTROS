import os
import io
import base64
from email.message import EmailMessage
from datetime import datetime
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash, send_file
)
from flask_session import Session
from PIL import Image
from fpdf import FPDF
import pandas as pd

# ————— Inicialización de la app —————
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'CAMBIÁ_POR_UNA_SECRETA')

# ————— Configuración de Flask‑Session —————
app.config['SESSION_TYPE']      = 'filesystem'
app.config['SESSION_FILE_DIR']  = './.flasksession'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
Session(app)

# ————— Filtro Jinja para Base64 —————
@app.template_filter('b64encode')
def b64encode_filter(data: bytes) -> str:
    """Convierte bytes a cadena base64 para incrustar imágenes."""
    return base64.b64encode(data).decode('utf-8')

# ————— Hacer enumerate y range disponibles en Jinja —————
app.jinja_env.globals.update(enumerate=enumerate, range=range)

# ————— Carga lista de pozos desde Excel —————
df = pd.read_excel("pozos.xlsx")
POZOS = df["POZO"].dropna().astype(str).tolist()

# ————— Función para generar el PDF —————
def generate_pdf(general, items, obs_final):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    # Cabecera
    pdf.cell(0,10, f"Informe - Pozo: {general['pozo']}", ln=True)
    pdf.cell(0, 8, f"Fecha: {general['fecha']}", ln=True)
    if general.get("obs_ini"):
        pdf.multi_cell(0,6, f"Obs. iniciales: {general['obs_ini']}")
    pdf.ln(4)

    # Margen y ancho útil
    lm = pdf.l_margin
    rm = pdf.r_margin
    usable_w = pdf.w - lm - rm

    for idx, item in enumerate(items, 1):
        # Título
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0,8,
                 f"Ítem {idx}: {item['tipo']} - {item['profundidad']}m - {item['estado']}",
                 ln=True)
        pdf.set_font("Arial", size=11)
        if item.get("comentario"):
            pdf.multi_cell(0,6, f"Comentario: {item['comentario']}")
        pdf.ln(2)

        fotos = item.get("fotos", [])
        n = len(fotos)
        if n:
            spacing = 5
            w_img = (usable_w - (n-1)*spacing) / n

            # Centramos el bloque
            group_w = n*w_img + (n-1)*spacing
            x_start = lm + (usable_w - group_w)/2
            y0 = pdf.get_y()

            # Insertamos imágenes y medimos sus alturas
            heights = []
            for i, foto in enumerate(fotos):
                # Medimos altura real vía Pillow
                img_data = foto["file"]
                with Image.open(io.BytesIO(img_data)) as img:
                    orig_w, orig_h = img.size
                h_img = orig_h * (w_img/orig_w)
                heights.append(h_img)

                x = x_start + i*(w_img+spacing)
                pdf.image(io.BytesIO(img_data), x=x, y=y0, w=w_img)

            max_h = max(heights)

            # Etiquetas: multi_cell envuelve el texto al ancho w_img
            pdf.set_font("Arial", size=10)
            y_label_end = y0
            for i, foto in enumerate(fotos):
                x = x_start + i*(w_img+spacing)
                pdf.set_xy(x, y0 + max_h + 1)
                pdf.multi_cell(w_img, 5, foto["tag"], align="C")
                # guardamos la posición más baja alcanzada
                y_label_end = max(y_label_end, pdf.get_y())

            # Reposicionamos cursor justo debajo del bloque completo
            y_end = y_label_end + 4
            pdf.set_xy(lm, y_end)

        pdf.ln(4)

    # Observaciones finales
    if obs_final:
        pdf.multi_cell(0,6, f"Obs. finales: {obs_final}")

    # Devolvemos buffer
    out = io.BytesIO()
    pdf.output(out)
    out.seek(0)
    return out

# ————— Rutas del wizard —————

@app.route("/", methods=["GET", "POST"])
def step1():
    if request.method == "POST":
        pozo   = request.form.get("pozo")
        fecha  = request.form.get("fecha")
        obs_ini = request.form.get("obs_ini")
        if not pozo or not fecha:
            flash("Completa los campos obligatorios.", "danger")
        else:
            session["general"] = {
                "pozo": pozo,
                "fecha": fecha,
                "obs_ini": obs_ini
            }
            session["items"] = []
            return redirect(url_for("step2"))
    return render_template("step1.html", pozos=POZOS)

@app.route("/step2", methods=["GET", "POST"])
def step2():
    if request.method == "POST":
        tipo        = request.form.get("tipo")
        profundidad = request.form.get("profundidad")
        estado      = request.form.get("estado")
        comentario  = request.form.get("comentario")
        if not tipo or not profundidad or not estado:
            flash("Completa los campos obligatorios.", "danger")
        else:
            item = {
                "tipo": tipo,
                "profundidad": profundidad,
                "estado": estado,
                "comentario": comentario,
                "fotos": []
            }
            items = session.get("items", [])
            items.append(item)
            session["items"] = items
            if "next" in request.form:
                return redirect(url_for("step3"))
            return redirect(url_for("step2"))
    return render_template("step2.html")

@app.route("/step3", methods=["GET", "POST"])
def step3():
    items = session.get("items", [])
    if request.method == "POST":
        updated = []
        for idx, item in enumerate(items):
            fotos = []
            for fidx in range(3):
                f = request.files.get(f"foto_{idx}_{fidx}")
                tag = request.form.get(f"tag_{idx}_{fidx}")
                if f:
                    fotos.append({"file": f.read(), "tag": tag})
            item["fotos"] = fotos
            updated.append(item)
        session["items"] = updated
        return redirect(url_for("step4"))
    return render_template("step3.html", items=items)

@app.route("/step4", methods=["GET", "POST"])
def step4():
    general = session.get("general", {})
    items   = session.get("items", [])
    if request.method == "POST":
        obs_final = request.form.get("obs_final")

        # 1) Botón “Descargar PDF”
        if "download" in request.form:
            pdf_buf = generate_pdf(general, items, obs_final)
            return send_file(
                pdf_buf,
                as_attachment=True,
                download_name="informe.pdf",
                mimetype="application/pdf"
            )

        # 2) Botón “Abrir en Outlook (con adjunto)”
        if "send" in request.form:
            # Genero el PDF
            pdf_buf = generate_pdf(general, items, obs_final)

            # Creo el mensaje .eml
            msg = EmailMessage()
            msg["Subject"] = f"Informe intervención — Pozo {general['pozo']}"
            msg["To"]      = "dest1@dominio.com, dest2@dominio.com"
            msg.set_content("Adjunto el informe de intervención. ¡Gracias!")

            # Adjunto el PDF
            msg.add_attachment(
                pdf_buf.getvalue(),
                maintype="application",
                subtype="pdf",
                filename="informe.pdf"
            )

            # Devuelvo un fichero .eml para que el cliente lo abra con Outlook
            eml_bytes = msg.as_bytes()
            return send_file(
                io.BytesIO(eml_bytes),
                as_attachment=True,
                download_name="informe.eml",
                mimetype="message/rfc822"
            )

    # GET: renderiza el formulario
    return render_template("step4.html", general=general, items=items)

if __name__ == "__main__":
    app.run()





