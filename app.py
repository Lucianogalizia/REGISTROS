import os
import io
import base64
from datetime import datetime
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash, send_file
)
from flask_session import Session
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
    pdf.cell(0, 10, f"Informe - Pozo: {general['pozo']}", ln=True)
    pdf.cell(0, 8,  f"Fecha: {general['fecha']}", ln=True)
    if general.get("obs_ini"):
        pdf.multi_cell(0, 6, f"Obs. iniciales: {general['obs_ini']}")
    pdf.ln(4)

    # Parámetros de margen
    page_width   = pdf.w
    left_margin  = pdf.l_margin
    right_margin = pdf.r_margin
    usable_width = page_width - left_margin - right_margin

    for idx, item in enumerate(items, 1):
        # Título de ítem
        pdf.set_font("Arial", "B", 12)
        pdf.cell(
            0, 8,
            f"Ítem {idx}: {item['tipo']} - {item['profundidad']}m - {item['estado']}",
            ln=True
        )
        pdf.set_font("Arial", size=11)
        if item.get("comentario"):
            pdf.multi_cell(0, 6, f"Comentario: {item['comentario']}")
        pdf.ln(2)

        fotos = item.get("fotos", [])
        n_imgs = len(fotos)
        if n_imgs:
            # Espacio entre imágenes en mm
            spacing = 5
            # Ancho de cada imagen
            w_img = (usable_width - (n_imgs - 1) * spacing) / n_imgs
            # Ancho total del grupo
            group_w = n_imgs * w_img + (n_imgs - 1) * spacing
            # Posición X inicial para centrar el grupo
            x_start = left_margin + (usable_width - group_w) / 2
            # Posición Y actual
            y0 = pdf.get_y()

            # Inserción de imágenes
            for i, foto in enumerate(fotos):
                x = x_start + i * (w_img + spacing)
                buf = io.BytesIO(foto["file"])
                pdf.image(buf, x=x, y=y0, w=w_img)

            # Avanzar por debajo de las imágenes
            # asumiendo relación altura ≈ 0.75 * ancho
            img_h = w_img * 0.75
            pdf.ln(img_h + 4)

            # Etiquetas centradas bajo cada imagen
            pdf.set_font("Arial", size=10)
            for i, foto in enumerate(fotos):
                x = x_start + i * (w_img + spacing)
                pdf.set_xy(x, y0 + img_h + 1)
                pdf.cell(w_img, 5, foto["tag"], align="C")
            pdf.ln(8)

    # Observaciones finales
    if obs_final:
        pdf.multi_cell(0, 6, f"Obs. finales: {obs_final}")

    # Volcar a buffer
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
    if request.method == "POST" and "download" in request.form:
        obs_final = request.form.get("obs_final")
        pdf_buf   = generate_pdf(general, items, obs_final)
        return send_file(
            pdf_buf,
            as_attachment=True,
            download_name="informe.pdf",
            mimetype="application/pdf"
        )
    return render_template("step4.html", general=general, items=items)

if __name__ == "__main__":
    app.run()





