"""
RentaAdmin — administración de arriendos de habitaciones.

Aplicación Flask de un solo archivo: modelos (SQLAlchemy/SQLite), rutas web,
API JSON para los gráficos (Chart.js) y generación de reportes PDF/CSV.
Ver README.md para instalación, despliegue y configuración.
"""

import os
import csv
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from io import BytesIO, StringIO
from urllib.parse import urlparse, urljoin

from dotenv import load_dotenv
from flask import (Flask, render_template, request, redirect, url_for,
                    session, flash, jsonify, send_file, send_from_directory)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import func, extract
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

COMPROBANTES_DIR = os.path.join(INSTANCE_DIR, "comprobantes")
os.makedirs(COMPROBANTES_DIR, exist_ok=True)
EXTENSIONES_COMPROBANTE_PERMITIDAS = {"pdf", "jpg", "jpeg", "png"}

DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(INSTANCE_DIR, "rentas.db"))
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(BASE_DIR, DB_PATH)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-cambiar")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB máximo por archivo subido

db = SQLAlchemy(app)
csrf = CSRFProtect(app)  # Protección CSRF para todas las rutas POST/PUT/PATCH/DELETE

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")

LONGITUD_MINIMA_CLAVE = 8  # mínimo de caracteres exigido para cualquier contraseña
ADMIN_PASSWORD_HASH = generate_password_hash(
    os.environ.get("ADMIN_PASSWORD", "admin123")
)

# Enlaces opcionales a un dashboard externo de BI (por ejemplo, Metabase) conectado
# a esta misma base de datos. Si no se configuran, los botones correspondientes
# simplemente no se muestran. Ver README para instrucciones de integración.
METABASE_URL_BALANCE = os.environ.get("METABASE_URL_BALANCE", "")
METABASE_URL_INGRESOS = os.environ.get("METABASE_URL_INGRESOS", "")
METABASE_URL_EGRESOS = os.environ.get("METABASE_URL_EGRESOS", "")

TIPOS_INGRESO = [
    ("arriendo", "Pago de arriendo"),
    ("multa", "Multa"),
    ("deposito", "Depósito / garantía"),
    ("otro", "Otro ingreso"),
]

TIPOS_EGRESO = [
    ("agua", "Agua"),
    ("gas", "Gas"),
    ("energia", "Energía"),
    ("internet_tv", "Internet / TV Cable"),
    ("impuestos", "Impuestos"),
    ("mantenimiento", "Mantenimiento / reparaciones"),
    ("aseo", "Aseo / insumos"),
    ("otro", "Otro egreso"),
]

PREGUNTAS_SEGURIDAD_SUGERIDAS = [
    "¿Cuál fue el nombre de tu primer trabajo?",
    "¿Cuál es el apodo que solo usa tu familia?",
    "¿Cuál fue el modelo de tu primer carro o moto?",
    "Escribe una pregunta propia que solo tú sepas responder",
]

# Pregunta que se muestra cuando el usuario del formulario de recuperación NO
# existe, para no revelar esa información por la sola presencia/ausencia de
# una pregunta real (ver recuperar_clave()).
PREGUNTA_SEGURIDAD_SENUELO = "¿Cuál es tu pregunta de seguridad?"


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------
class Habitacion(db.Model):
    __tablename__ = "habitaciones"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False)
    tarifa_mensual = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    notas = db.Column(db.String(255))

    inquilinos = db.relationship("Inquilino", backref="habitacion", lazy=True)

    @property
    def inquilino_activo(self):
        for i in self.inquilinos:
            if i.activo:
                return i
        return None


class Inquilino(db.Model):
    __tablename__ = "inquilinos"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    documento = db.Column(db.String(40))
    telefono = db.Column(db.String(40))
    email = db.Column(db.String(120))
    habitacion_id = db.Column(db.Integer, db.ForeignKey("habitaciones.id"), nullable=True)
    fecha_ingreso = db.Column(db.Date, default=date.today)
    fecha_salida = db.Column(db.Date, nullable=True)
    activo = db.Column(db.Boolean, default=True)


class Ingreso(db.Model):
    __tablename__ = "ingresos"
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    tipo = db.Column(db.String(40), nullable=False)
    habitacion_id = db.Column(db.Integer, db.ForeignKey("habitaciones.id"), nullable=True)
    inquilino_id = db.Column(db.Integer, db.ForeignKey("inquilinos.id"), nullable=True)
    concepto = db.Column(db.String(255))
    monto = db.Column(db.Numeric(12, 2), nullable=False)
    comprobante = db.Column(db.String(255))

    habitacion = db.relationship("Habitacion")
    inquilino = db.relationship("Inquilino")


class Egreso(db.Model):
    __tablename__ = "egresos"
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    tipo = db.Column(db.String(40), nullable=False)
    concepto = db.Column(db.String(255))
    monto = db.Column(db.Numeric(12, 2), nullable=False)
    comprobante = db.Column(db.String(255))


class EnlacePago(db.Model):
    __tablename__ = "enlaces_pago"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False)
    url = db.Column(db.String(500), nullable=False)


class Usuario(db.Model):
    __tablename__ = "usuarios"
    id = db.Column(db.Integer, primary_key=True)
    nombre_usuario = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    pregunta_seguridad = db.Column(db.String(255), nullable=False)
    respuesta_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default="usuario")  # "admin" o "usuario"
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, clave):
        self.password_hash = generate_password_hash(clave)

    def check_password(self, clave):
        return check_password_hash(self.password_hash, clave)

    def set_respuesta(self, respuesta):
        self.respuesta_hash = generate_password_hash(respuesta.strip().lower())

    def check_respuesta(self, respuesta):
        return check_password_hash(self.respuesta_hash, respuesta.strip().lower())


# --------------------------------------------------------------------------
# Autenticación simple (usuario único, definido por variables de entorno)
# --------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logueado"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    """Como login_required, pero además exige rol de administrador.
    Úsalo en operaciones sensibles (gestión de usuarios, por ejemplo)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logueado"):
            return redirect(url_for("login", next=request.path))
        if session.get("rol") != "admin":
            flash("Esa sección es solo para administradores.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_metabase_urls():
    """Pone los enlaces opcionales a Metabase (y otras constantes de configuración)
    disponibles en todas las plantillas sin tener que pasarlas en cada ruta."""
    return dict(
        metabase_url_balance=METABASE_URL_BALANCE,
        metabase_url_ingresos=METABASE_URL_INGRESOS,
        metabase_url_egresos=METABASE_URL_EGRESOS,
        longitud_minima_clave=LONGITUD_MINIMA_CLAVE,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "")

        autenticado = False
        rol = "usuario"
        if usuario == ADMIN_USER and check_password_hash(ADMIN_PASSWORD_HASH, clave):
            autenticado = True
            rol = "admin"  # El usuario administrador definido en .env siempre es admin
        else:
            u = Usuario.query.filter_by(nombre_usuario=usuario).first()
            if u and u.check_password(clave):
                autenticado = True
                rol = u.rol

        if autenticado:
            session["logueado"] = True
            session["nombre_usuario"] = usuario
            session["rol"] = rol
            destino = request.args.get("next")
            if not es_redireccion_segura(destino):
                destino = url_for("dashboard")
            return redirect(destino)
        flash("Usuario o contraseña incorrectos.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/recuperar-clave", methods=["GET", "POST"])
def recuperar_clave():
    paso = 1
    pregunta_mostrar = None

    if request.method == "POST":
        etapa = request.form.get("etapa")

        if etapa == "buscar":
            nombre_usuario = request.form.get("usuario", "").strip()
            u = None
            if nombre_usuario and nombre_usuario != ADMIN_USER:
                u = Usuario.query.filter_by(nombre_usuario=nombre_usuario).first()
            # Nunca revelamos si el usuario existe: siempre se avanza al paso 2,
            # mostrando una pregunta real (si existe) o una genérica (si no),
            # para no permitir enumerar cuentas por el mensaje de respuesta.
            session["recuperar_usuario_id"] = u.id if u else None
            paso = 2
            pregunta_mostrar = u.pregunta_seguridad if u else PREGUNTA_SEGURIDAD_SENUELO

        elif etapa == "restablecer":
            usuario_id = session.get("recuperar_usuario_id")
            u = Usuario.query.get(usuario_id) if usuario_id else None
            respuesta = request.form.get("respuesta", "")
            nueva_clave = request.form.get("nueva_clave", "")
            confirmar = request.form.get("confirmar_clave", "")

            # Mismo mensaje tanto si la cuenta no existe (u is None) como si la
            # respuesta es incorrecta: desde afuera, ambos casos se ven iguales.
            if not u or not u.check_respuesta(respuesta):
                flash("La respuesta de seguridad no es correcta.", "danger")
                paso = 2
                pregunta_mostrar = u.pregunta_seguridad if u else PREGUNTA_SEGURIDAD_SENUELO
            elif len(nueva_clave) < LONGITUD_MINIMA_CLAVE:
                flash(f"La nueva contraseña debe tener al menos {LONGITUD_MINIMA_CLAVE} caracteres.", "danger")
                paso = 2
                pregunta_mostrar = u.pregunta_seguridad
            elif nueva_clave != confirmar:
                flash("Las contraseñas no coinciden.", "danger")
                paso = 2
                pregunta_mostrar = u.pregunta_seguridad
            else:
                u.set_password(nueva_clave)
                db.session.commit()
                session.pop("recuperar_usuario_id", None)
                flash("Contraseña actualizada. Ya puedes iniciar sesión.", "success")
                return redirect(url_for("login"))

    # Si venimos de un GET con una recuperación en curso (por ejemplo, tras
    # recargar la página), retomamos el paso 2 con la misma pregunta.
    if paso == 1 and "recuperar_usuario_id" in session and request.method == "GET":
        usuario_id = session.get("recuperar_usuario_id")
        u = Usuario.query.get(usuario_id) if usuario_id else None
        paso = 2
        pregunta_mostrar = u.pregunta_seguridad if u else PREGUNTA_SEGURIDAD_SENUELO

    return render_template("recuperar_clave.html", paso=paso, pregunta=pregunta_mostrar)


# --------------------------------------------------------------------------
# Utilidades de fechas / consultas
# --------------------------------------------------------------------------
def es_redireccion_segura(destino):
    """Evita open redirects: solo permite redirigir a rutas internas de esta
    misma aplicación (mismo esquema y mismo host que la petición actual)."""
    if not destino:
        return False
    referencia = urlparse(request.host_url)
    candidato = urlparse(urljoin(request.host_url, destino))
    return candidato.scheme in ("http", "https") and candidato.netloc == referencia.netloc


def parse_id(valor):
    """Convierte un ID de formulario a entero de forma segura. Devuelve None
    si viene vacío o si no es un entero válido (nunca lanza excepción)."""
    if valor is None or str(valor).strip() == "":
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def obtener_habitacion(habitacion_id_raw):
    """Convierte y valida que la habitación exista de verdad en la base de datos.
    Devuelve el objeto Habitacion, o None si el id es inválido o no existe."""
    hid = parse_id(habitacion_id_raw)
    if hid is None:
        return None
    return Habitacion.query.get(hid)


def obtener_inquilino(inquilino_id_raw):
    """Igual que obtener_habitacion, pero para inquilinos."""
    iid = parse_id(inquilino_id_raw)
    if iid is None:
        return None
    return Inquilino.query.get(iid)


def ocupante_activo_de(habitacion_id, excluir_inquilino_id=None):
    """Regla de negocio: una habitación solo puede tener un inquilino activo.
    Devuelve el inquilino activo que ya ocupa esa habitación (si hay alguno),
    excluyendo opcionalmente al propio inquilino que se está editando/asignando
    (para poder guardar cambios de alguien que ya está en esa habitación)."""
    consulta = Inquilino.query.filter_by(habitacion_id=habitacion_id, activo=True)
    if excluir_inquilino_id is not None:
        consulta = consulta.filter(Inquilino.id != excluir_inquilino_id)
    return consulta.first()


def tipo_valido(valor, lista_tipos):
    """Comprueba que 'valor' sea una de las claves permitidas en lista_tipos
    (TIPOS_INGRESO, TIPOS_EGRESO, etc.), en vez de confiar en que el <select>
    del navegador no fue manipulado."""
    return valor in dict(lista_tipos)


def parse_fecha(valor, por_defecto=None):
    if not valor:
        return por_defecto
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError:
        return por_defecto


def parse_monto(valor, por_defecto=None):
    """Convierte un valor de formulario a Decimal con 2 decimales, de forma segura.
    Usar Decimal (en vez de float) para dinero evita errores de redondeo binario
    como 0.1 + 0.2 != 0.3 exacto."""
    if valor is None or str(valor).strip() == "":
        return por_defecto
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return por_defecto


def extension_permitida(nombre_archivo):
    return "." in nombre_archivo and nombre_archivo.rsplit(".", 1)[1].lower() in EXTENSIONES_COMPROBANTE_PERMITIDAS


def guardar_comprobante(archivo):
    """Guarda un archivo subido (factura/recibo) en instance/comprobantes y devuelve
    el nombre con el que quedó guardado, o None si no se envió un archivo válido."""
    if not archivo or archivo.filename == "":
        return None
    if not extension_permitida(archivo.filename):
        flash("El comprobante debe ser un archivo PDF, JPG o PNG.", "danger")
        return None
    nombre_seguro = secure_filename(archivo.filename)
    nombre_guardado = f"{uuid.uuid4().hex}_{nombre_seguro}"
    archivo.save(os.path.join(COMPROBANTES_DIR, nombre_guardado))
    return nombre_guardado


def eliminar_archivo_comprobante(nombre_archivo):
    """Borra físicamente el archivo de un comprobante de instance/comprobantes/,
    para no dejar huérfanos cuando se elimina el ingreso/egreso que lo referenciaba.
    Nunca lanza excepción: si el archivo ya no existe, simplemente no hace nada."""
    if not nombre_archivo:
        return
    ruta = os.path.normpath(os.path.join(COMPROBANTES_DIR, nombre_archivo))
    # Defensivo: nunca borrar nada fuera de la carpeta de comprobantes
    if not ruta.startswith(os.path.normpath(COMPROBANTES_DIR) + os.sep):
        return
    try:
        os.remove(ruta)
    except FileNotFoundError:
        pass


def total(query, campo):
    """Suma un campo monetario (Decimal). Usa 0 (no 0.0) como valor de reemplazo
    para no mezclar float con Decimal en operaciones posteriores."""
    return query.with_entities(func.coalesce(func.sum(campo), 0)).scalar() or Decimal("0")


def estadisticas_lista(valores):
    """Máximo, mínimo y promedio de una lista de números ya cargada en Python
    (útil cuando ya se filtró/combinó la información en memoria)."""
    if not valores:
        return {"maximo": Decimal("0"), "minimo": Decimal("0"), "promedio": Decimal("0")}
    return {"maximo": max(valores), "minimo": min(valores), "promedio": sum(valores) / len(valores)}


def ultimos_12_meses():
    """Lista de 12 tuplas (año, mes), del más antiguo al más reciente, terminando en el mes actual."""
    meses = []
    hoy = date.today()
    y, m = hoy.year, hoy.month
    for _ in range(12):
        meses.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    meses.reverse()
    return meses


NOMBRES_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                  "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def mes_anterior_a(anio, mes):
    """Devuelve (año, mes) del mes calendario inmediatamente anterior."""
    if mes == 1:
        return anio - 1, 12
    return anio, mes - 1


def variacion_porcentual(actual, anterior):
    """Porcentaje de cambio de 'anterior' a 'actual'. Devuelve None si no se
    puede calcular (el mes anterior no tuvo movimientos), para no dividir por cero."""
    if anterior == 0:
        return None
    return float((actual - anterior) / anterior * 100)


@app.template_filter("tipo_label")
def tipo_label_filter(valor, lista_tipos):
    """Convierte el valor interno de un tipo (ej. 'agua') en su etiqueta legible."""
    return dict(lista_tipos).get(valor, valor)


# --------------------------------------------------------------------------
# Generación de reportes PDF
# --------------------------------------------------------------------------
def generar_pdf(titulo, subtitulo, encabezados, filas, total_label=None, total_valor=None):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=40, bottomMargin=40)
    estilos = getSampleStyleSheet()
    elementos = [Paragraph(titulo, estilos["Title"])]
    if subtitulo:
        elementos.append(Paragraph(subtitulo, estilos["Normal"]))
    elementos.append(Spacer(1, 16))

    datos_tabla = [encabezados] + filas
    tabla = Table(datos_tabla, repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d6efd")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f9")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elementos.append(tabla)

    if total_label is not None:
        elementos.append(Spacer(1, 14))
        elementos.append(Paragraph(f"<b>{total_label}: {total_valor}</b>", estilos["Normal"]))

    doc.build(elementos)
    buffer.seek(0)
    return buffer


def generar_csv(encabezados, filas, nombre_archivo):
    """Genera un CSV en memoria, ideal para abrir en Excel/Google Sheets o
    conectarlo a una herramienta de análisis de datos (Looker Studio, Metabase, etc.)."""
    buffer_texto = StringIO()
    escritor = csv.writer(buffer_texto)
    escritor.writerow(encabezados)
    escritor.writerows(filas)
    # utf-8-sig para que Excel reconozca bien las tildes y la Ñ al abrir el archivo
    buffer_bytes = BytesIO(buffer_texto.getvalue().encode("utf-8-sig"))
    return send_file(buffer_bytes, mimetype="text/csv", as_attachment=True, download_name=nombre_archivo)


@app.route("/historico/csv")
@login_required
def historico_csv():
    desde = parse_fecha(request.args.get("desde"))
    hasta = parse_fecha(request.args.get("hasta"))
    tipo_mov = request.args.get("tipo_mov", "todos")
    habitacion_id = request.args.get("habitacion_id", type=int)

    filas = []
    if tipo_mov in ("todos", "ingresos"):
        q = Ingreso.query
        if desde:
            q = q.filter(Ingreso.fecha >= desde)
        if hasta:
            q = q.filter(Ingreso.fecha <= hasta)
        if habitacion_id:
            q = q.filter(Ingreso.habitacion_id == habitacion_id)
        for i in q.all():
            filas.append([i.fecha.isoformat(), "Ingreso", dict(TIPOS_INGRESO).get(i.tipo, i.tipo),
                          i.habitacion.nombre if i.habitacion else "", i.concepto or "", i.monto])
    if tipo_mov in ("todos", "egresos") and not habitacion_id:
        q = Egreso.query
        if desde:
            q = q.filter(Egreso.fecha >= desde)
        if hasta:
            q = q.filter(Egreso.fecha <= hasta)
        for e in q.all():
            filas.append([e.fecha.isoformat(), "Egreso", dict(TIPOS_EGRESO).get(e.tipo, e.tipo),
                          "", e.concepto or "", -e.monto])

    filas.sort(key=lambda f: f[0], reverse=True)
    return generar_csv(
        ["Fecha", "Movimiento", "Tipo", "Habitacion", "Concepto", "Monto"],
        filas,
        "historico_movimientos.csv",
    )


@app.route("/historico/pdf")
@login_required
def historico_pdf():
    desde = parse_fecha(request.args.get("desde"))
    hasta = parse_fecha(request.args.get("hasta"))
    tipo_mov = request.args.get("tipo_mov", "todos")
    habitacion_id = request.args.get("habitacion_id", type=int)

    movimientos = []
    if tipo_mov in ("todos", "ingresos"):
        q = Ingreso.query
        if desde:
            q = q.filter(Ingreso.fecha >= desde)
        if hasta:
            q = q.filter(Ingreso.fecha <= hasta)
        if habitacion_id:
            q = q.filter(Ingreso.habitacion_id == habitacion_id)
        for i in q.all():
            movimientos.append((i.fecha, "Ingreso", dict(TIPOS_INGRESO).get(i.tipo, i.tipo),
                                 i.habitacion.nombre if i.habitacion else "-", i.concepto or "-", i.monto))
    if tipo_mov in ("todos", "egresos") and not habitacion_id:
        q = Egreso.query
        if desde:
            q = q.filter(Egreso.fecha >= desde)
        if hasta:
            q = q.filter(Egreso.fecha <= hasta)
        for e in q.all():
            movimientos.append((e.fecha, "Egreso", dict(TIPOS_EGRESO).get(e.tipo, e.tipo),
                                 "-", e.concepto or "-", -e.monto))

    movimientos.sort(key=lambda m: m[0], reverse=True)
    total_periodo = sum(m[5] for m in movimientos)
    filas = [[m[0].strftime("%d/%m/%Y"), m[1], m[2], m[3], m[4], f"${m[5]:,.0f}"] for m in movimientos]

    buffer = generar_pdf(
        "Histórico de movimientos",
        f"Generado el {date.today().strftime('%d/%m/%Y')}",
        ["Fecha", "Movimiento", "Tipo", "Habitación", "Concepto", "Monto"],
        filas,
        total_label="Total del período",
        total_valor=f"${total_periodo:,.0f}",
    )
    return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                      download_name="historico_movimientos.pdf")


@app.route("/egresos/historico/csv")
@login_required
def historico_egresos_csv():
    tipo = request.args.get("tipo", "todos")
    desde = parse_fecha(request.args.get("desde"))
    hasta = parse_fecha(request.args.get("hasta"))

    q = Egreso.query
    if tipo != "todos":
        q = q.filter(Egreso.tipo == tipo)
    if desde:
        q = q.filter(Egreso.fecha >= desde)
    if hasta:
        q = q.filter(Egreso.fecha <= hasta)
    lista = q.order_by(Egreso.fecha.desc()).all()

    filas = [[e.fecha.isoformat(), dict(TIPOS_EGRESO).get(e.tipo, e.tipo), e.concepto or "", e.monto] for e in lista]
    return generar_csv(["Fecha", "Tipo", "Concepto", "Monto"], filas, "historico_egresos.csv")


@app.route("/egresos/historico/pdf")
@login_required
def historico_egresos_pdf():
    tipo = request.args.get("tipo", "todos")
    desde = parse_fecha(request.args.get("desde"))
    hasta = parse_fecha(request.args.get("hasta"))

    q = Egreso.query
    if tipo != "todos":
        q = q.filter(Egreso.tipo == tipo)
    if desde:
        q = q.filter(Egreso.fecha >= desde)
    if hasta:
        q = q.filter(Egreso.fecha <= hasta)
    lista = q.order_by(Egreso.fecha.desc()).all()
    total_filtrado = sum(e.monto for e in lista)

    filas = [[e.fecha.strftime("%d/%m/%Y"), dict(TIPOS_EGRESO).get(e.tipo, e.tipo),
              e.concepto or "-", f"${e.monto:,.0f}"] for e in lista]

    etiqueta_tipo = dict(TIPOS_EGRESO).get(tipo, "Todos los tipos") if tipo != "todos" else "Todos los tipos"
    buffer = generar_pdf(
        "Histórico de egresos",
        f"Filtro: {etiqueta_tipo} — Generado el {date.today().strftime('%d/%m/%Y')}",
        ["Fecha", "Tipo", "Concepto", "Monto"],
        filas,
        total_label="Total filtrado",
        total_valor=f"${total_filtrado:,.0f}",
    )
    return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                      download_name="historico_egresos.pdf")


@app.route("/balance/pdf")
@login_required
def balance_pdf():
    meses = ultimos_12_meses()

    filas = []
    total_ingresos, total_egresos = Decimal("0"), Decimal("0")
    acumulado = Decimal("0")
    for y, m in meses:
        ti = total(Ingreso.query.filter(extract("year", Ingreso.fecha) == y,
                                         extract("month", Ingreso.fecha) == m), Ingreso.monto)
        te = total(Egreso.query.filter(extract("year", Egreso.fecha) == y,
                                        extract("month", Egreso.fecha) == m), Egreso.monto)
        total_ingresos += ti
        total_egresos += te
        acumulado += (ti - te)
        filas.append([f"{m:02d}/{y}", f"${ti:,.0f}", f"${te:,.0f}", f"${ti - te:,.0f}", f"${acumulado:,.0f}"])

    buffer = generar_pdf(
        "Balance mensual (últimos 12 meses)",
        f"Generado el {date.today().strftime('%d/%m/%Y')}",
        ["Mes", "Ingresos", "Egresos", "Balance del mes", "Balance acumulado"],
        filas,
        total_label="Balance acumulado del período",
        total_valor=f"${total_ingresos - total_egresos:,.0f}",
    )
    return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                      download_name="balance_mensual.pdf")


# --------------------------------------------------------------------------
# Usuarios del sistema (cuentas de acceso a la aplicación)
# --------------------------------------------------------------------------
@app.route("/usuarios", methods=["GET", "POST"])
@admin_required
def usuarios():
    if request.method == "POST":
        nombre_usuario = request.form.get("nombre_usuario", "").strip()
        clave = request.form.get("clave", "")
        pregunta = request.form.get("pregunta_seguridad", "").strip()
        respuesta = request.form.get("respuesta_seguridad", "").strip()
        rol = request.form.get("rol", "usuario")
        if rol not in ("admin", "usuario"):
            rol = "usuario"

        if not nombre_usuario or not clave or not pregunta or not respuesta:
            flash("Todos los campos son obligatorios para crear un usuario.", "danger")
        elif len(clave) < LONGITUD_MINIMA_CLAVE:
            flash(f"La contraseña debe tener al menos {LONGITUD_MINIMA_CLAVE} caracteres.", "danger")
        elif nombre_usuario == ADMIN_USER or Usuario.query.filter_by(nombre_usuario=nombre_usuario).first():
            flash("Ese nombre de usuario ya está en uso.", "danger")
        else:
            u = Usuario(nombre_usuario=nombre_usuario, pregunta_seguridad=pregunta, rol=rol)
            u.set_password(clave)
            u.set_respuesta(respuesta)
            db.session.add(u)
            db.session.commit()
            flash(f"Usuario '{nombre_usuario}' creado correctamente.", "success")
        return redirect(url_for("usuarios"))

    lista = Usuario.query.order_by(Usuario.nombre_usuario).all()
    return render_template("usuarios.html", usuarios=lista, preguntas=PREGUNTAS_SEGURIDAD_SUGERIDAS,
                            admin_user=ADMIN_USER)


@app.route("/usuarios/<int:usuario_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_usuario(usuario_id):
    u = Usuario.query.get_or_404(usuario_id)
    db.session.delete(u)
    db.session.commit()
    flash(f"Usuario '{u.nombre_usuario}' eliminado.", "warning")
    return redirect(url_for("usuarios"))


@app.route("/usuarios/<int:usuario_id>/cambiar-clave", methods=["POST"])
@admin_required
def cambiar_clave_usuario(usuario_id):
    u = Usuario.query.get_or_404(usuario_id)
    nueva_clave = request.form.get("nueva_clave", "")
    if len(nueva_clave) < LONGITUD_MINIMA_CLAVE:
        flash(f"La contraseña debe tener al menos {LONGITUD_MINIMA_CLAVE} caracteres.", "danger")
    else:
        u.set_password(nueva_clave)
        db.session.commit()
        flash(f"Contraseña de '{u.nombre_usuario}' actualizada.", "success")
    return redirect(url_for("usuarios"))


@app.route("/usuarios/<int:usuario_id>/cambiar-rol", methods=["POST"])
@admin_required
def cambiar_rol_usuario(usuario_id):
    u = Usuario.query.get_or_404(usuario_id)
    nuevo_rol = request.form.get("rol")
    if nuevo_rol not in ("admin", "usuario"):
        flash("Rol inválido.", "danger")
    else:
        u.rol = nuevo_rol
        db.session.commit()
        flash(f"Rol de '{u.nombre_usuario}' actualizado a {nuevo_rol}.", "success")
    return redirect(url_for("usuarios"))


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    hoy = date.today()
    mes_actual = hoy.month
    anio_actual = hoy.year
    anio_anterior, mes_anterior = mes_anterior_a(anio_actual, mes_actual)

    ingresos_mes = Ingreso.query.filter(
        extract("month", Ingreso.fecha) == mes_actual,
        extract("year", Ingreso.fecha) == anio_actual,
    )
    egresos_mes = Egreso.query.filter(
        extract("month", Egreso.fecha) == mes_actual,
        extract("year", Egreso.fecha) == anio_actual,
    )
    ingresos_mes_anterior_q = Ingreso.query.filter(
        extract("month", Ingreso.fecha) == mes_anterior,
        extract("year", Ingreso.fecha) == anio_anterior,
    )
    egresos_mes_anterior_q = Egreso.query.filter(
        extract("month", Egreso.fecha) == mes_anterior,
        extract("year", Egreso.fecha) == anio_anterior,
    )

    total_ingresos_mes = total(ingresos_mes, Ingreso.monto)
    total_egresos_mes = total(egresos_mes, Egreso.monto)
    balance_mes = total_ingresos_mes - total_egresos_mes

    total_ingresos_mes_anterior = total(ingresos_mes_anterior_q, Ingreso.monto)
    total_egresos_mes_anterior = total(egresos_mes_anterior_q, Egreso.monto)
    balance_mes_anterior = total_ingresos_mes_anterior - total_egresos_mes_anterior

    variacion_ingresos = variacion_porcentual(total_ingresos_mes, total_ingresos_mes_anterior)
    variacion_egresos = variacion_porcentual(total_egresos_mes, total_egresos_mes_anterior)
    variacion_balance = variacion_porcentual(balance_mes, balance_mes_anterior)

    total_ingresos_hist = total(Ingreso.query, Ingreso.monto)
    total_egresos_hist = total(Egreso.query, Egreso.monto)
    balance_hist = total_ingresos_hist - total_egresos_hist

    habitaciones = Habitacion.query.order_by(Habitacion.nombre).all()
    ocupadas = sum(1 for h in habitaciones if h.inquilino_activo)
    total_habitaciones = len(habitaciones)
    disponibles = total_habitaciones - ocupadas
    porcentaje_ocupacion = round((ocupadas / total_habitaciones) * 100) if total_habitaciones else 0

    return render_template(
        "dashboard.html",
        total_ingresos_mes=total_ingresos_mes,
        total_egresos_mes=total_egresos_mes,
        balance_mes=balance_mes,
        variacion_ingresos=variacion_ingresos,
        variacion_egresos=variacion_egresos,
        variacion_balance=variacion_balance,
        nombre_mes_actual=NOMBRES_MESES[mes_actual - 1],
        nombre_mes_anterior=NOMBRES_MESES[mes_anterior - 1],
        total_ingresos_hist=total_ingresos_hist,
        total_egresos_hist=total_egresos_hist,
        balance_hist=balance_hist,
        habitaciones=habitaciones,
        ocupadas=ocupadas,
        disponibles=disponibles,
        porcentaje_ocupacion=porcentaje_ocupacion,
        total_habitaciones=total_habitaciones,
    )


# --------------------------------------------------------------------------
# Habitaciones e inquilinos
# --------------------------------------------------------------------------
@app.route("/habitaciones", methods=["GET", "POST"])
@login_required
def habitaciones():
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "crear_habitacion":
            h = Habitacion(
                nombre=request.form["nombre"].strip(),
                tarifa_mensual=parse_monto(request.form.get("tarifa_mensual"), Decimal("0")),
                notas=request.form.get("notas", "").strip(),
            )
            db.session.add(h)
            db.session.commit()
            flash(f"Habitación '{h.nombre}' creada.", "success")
        elif accion == "crear_inquilino":
            habitacion_id_raw = request.form.get("habitacion_id")
            habitacion_elegida = obtener_habitacion(habitacion_id_raw) if habitacion_id_raw else None
            if habitacion_id_raw and habitacion_elegida is None:
                flash("La habitación seleccionada no existe.", "danger")
                return redirect(url_for("habitaciones"))
            if habitacion_elegida:
                ocupante = ocupante_activo_de(habitacion_elegida.id)
                if ocupante:
                    flash(f"La habitación '{habitacion_elegida.nombre}' ya tiene un inquilino activo "
                          f"({ocupante.nombre}). Registra su salida antes de asignar otro.", "danger")
                    return redirect(url_for("habitaciones"))
            i = Inquilino(
                nombre=request.form["nombre"].strip(),
                documento=request.form.get("documento", "").strip(),
                telefono=request.form.get("telefono", "").strip(),
                email=request.form.get("email", "").strip(),
                habitacion_id=habitacion_elegida.id if habitacion_elegida else None,
                fecha_ingreso=parse_fecha(request.form.get("fecha_ingreso"), date.today()),
                activo=True,
            )
            db.session.add(i)
            db.session.commit()
            if i.habitacion_id:
                flash(f"Inquilino '{i.nombre}' creado y asignado a una habitación.", "success")
            else:
                flash(f"Inquilino '{i.nombre}' creado sin habitación asignada.", "success")
        return redirect(url_for("habitaciones"))

    lista = Habitacion.query.order_by(Habitacion.nombre).all()
    sin_asignar = Inquilino.query.filter_by(habitacion_id=None, activo=True).order_by(Inquilino.nombre).all()
    return render_template("habitaciones.html", habitaciones=lista, sin_asignar=sin_asignar)


@app.route("/inquilinos/<int:inquilino_id>/asignar", methods=["POST"])
@login_required
def asignar_inquilino(inquilino_id):
    i = Inquilino.query.get_or_404(inquilino_id)
    habitacion = obtener_habitacion(request.form.get("habitacion_id"))
    if habitacion is None:
        flash("Selecciona una habitación válida.", "danger")
        return redirect(url_for("habitaciones"))
    if i.activo:
        ocupante = ocupante_activo_de(habitacion.id, excluir_inquilino_id=i.id)
        if ocupante:
            flash(f"La habitación '{habitacion.nombre}' ya tiene un inquilino activo "
                  f"({ocupante.nombre}). Registra su salida antes de asignar otro.", "danger")
            return redirect(url_for("habitaciones"))
    i.habitacion_id = habitacion.id
    db.session.commit()
    flash(f"{i.nombre} fue asignado a la habitación seleccionada.", "success")
    return redirect(url_for("habitaciones"))


@app.route("/inquilinos/<int:inquilino_id>/desasignar", methods=["POST"])
@login_required
def desasignar_inquilino(inquilino_id):
    i = Inquilino.query.get_or_404(inquilino_id)
    i.habitacion_id = None
    db.session.commit()
    flash(f"{i.nombre} quedó sin habitación asignada (sigue activo).", "info")
    return redirect(url_for("habitaciones"))


@app.route("/habitaciones/<int:habitacion_id>/editar", methods=["GET", "POST"])
@login_required
def editar_habitacion(habitacion_id):
    h = Habitacion.query.get_or_404(habitacion_id)
    if request.method == "POST":
        h.nombre = request.form["nombre"].strip()
        h.tarifa_mensual = parse_monto(request.form.get("tarifa_mensual"), Decimal("0"))
        h.notas = request.form.get("notas", "").strip()
        db.session.commit()
        flash(f"Habitación '{h.nombre}' actualizada.", "success")
        return redirect(url_for("habitaciones"))
    return render_template("editar_habitacion.html", h=h)


@app.route("/inquilinos/<int:inquilino_id>/editar", methods=["GET", "POST"])
@login_required
def editar_inquilino(inquilino_id):
    i = Inquilino.query.get_or_404(inquilino_id)
    habitaciones_list = Habitacion.query.order_by(Habitacion.nombre).all()
    if request.method == "POST":
        habitacion_id_raw = request.form.get("habitacion_id")
        habitacion_elegida = obtener_habitacion(habitacion_id_raw) if habitacion_id_raw else None
        if habitacion_id_raw and habitacion_elegida is None:
            flash("La habitación seleccionada no existe.", "danger")
            return redirect(url_for("editar_inquilino", inquilino_id=inquilino_id))
        nuevo_activo = request.form.get("activo") == "on"
        if habitacion_elegida and nuevo_activo:
            ocupante = ocupante_activo_de(habitacion_elegida.id, excluir_inquilino_id=i.id)
            if ocupante:
                flash(f"La habitación '{habitacion_elegida.nombre}' ya tiene un inquilino activo "
                      f"({ocupante.nombre}). Registra su salida antes de asignar otro.", "danger")
                return redirect(url_for("editar_inquilino", inquilino_id=inquilino_id))
        i.nombre = request.form["nombre"].strip()
        i.documento = request.form.get("documento", "").strip()
        i.telefono = request.form.get("telefono", "").strip()
        i.email = request.form.get("email", "").strip()
        i.habitacion_id = habitacion_elegida.id if habitacion_elegida else None
        i.fecha_ingreso = parse_fecha(request.form.get("fecha_ingreso"), i.fecha_ingreso)
        i.activo = nuevo_activo
        db.session.commit()
        flash(f"Inquilino '{i.nombre}' actualizado.", "success")
        return redirect(url_for("habitaciones"))
    return render_template("editar_inquilino.html", i=i, habitaciones=habitaciones_list)


@app.route("/habitaciones/<int:habitacion_id>/eliminar", methods=["POST"])
@login_required
def eliminar_habitacion(habitacion_id):
    h = Habitacion.query.get_or_404(habitacion_id)
    # Desvincular ingresos históricos (se conservan como registro, sin habitación asociada)
    Ingreso.query.filter_by(habitacion_id=h.id).update({"habitacion_id": None})
    # Nunca se borra físicamente a un inquilino (perdería su historial de ingresos):
    # se desvincula de la habitación y, si estaba activo, se le registra la salida.
    hoy = date.today()
    inquilinos_afectados = Inquilino.query.filter_by(habitacion_id=h.id).all()
    for i in inquilinos_afectados:
        i.habitacion_id = None
        if i.activo:
            i.activo = False
            i.fecha_salida = hoy
    db.session.delete(h)
    db.session.commit()
    if inquilinos_afectados:
        flash(f"Habitación eliminada. {len(inquilinos_afectados)} inquilino(s) quedaron "
              f"sin habitación e inactivos (su historial se conserva).", "warning")
    else:
        flash("Habitación eliminada.", "warning")
    return redirect(url_for("habitaciones"))


@app.route("/inquilinos/<int:inquilino_id>/salida", methods=["POST"])
@login_required
def marcar_salida(inquilino_id):
    i = Inquilino.query.get_or_404(inquilino_id)
    i.activo = False
    i.fecha_salida = date.today()
    db.session.commit()
    flash(f"Se registró la salida de {i.nombre}.", "info")
    return redirect(url_for("habitaciones"))


@app.route("/comprobantes/<path:nombre_archivo>")
@login_required
def ver_comprobante(nombre_archivo):
    return send_from_directory(COMPROBANTES_DIR, nombre_archivo)


# --------------------------------------------------------------------------
# Ingresos
# --------------------------------------------------------------------------
@app.route("/ingresos", methods=["GET", "POST"])
@login_required
def ingresos():
    if request.method == "POST":
        habitacion_id_raw = request.form.get("habitacion_id")
        inquilino_id_raw = request.form.get("inquilino_id")

        if not tipo_valido(request.form.get("tipo"), TIPOS_INGRESO):
            flash("El tipo de ingreso no es válido.", "danger")
            return redirect(url_for("ingresos"))

        inquilino_elegido = obtener_inquilino(inquilino_id_raw)
        if inquilino_elegido is None:
            flash("Debes seleccionar un inquilino válido para registrar el ingreso.", "danger")
            return redirect(url_for("ingresos"))

        habitacion_elegida = obtener_habitacion(habitacion_id_raw) if habitacion_id_raw else None
        if habitacion_id_raw and habitacion_elegida is None:
            flash("La habitación seleccionada no existe.", "danger")
            return redirect(url_for("ingresos"))

        monto = parse_monto(request.form.get("monto"))
        if monto is None or monto <= 0:
            flash("El monto ingresado no es válido.", "danger")
            return redirect(url_for("ingresos"))
        comprobante_nombre = guardar_comprobante(request.files.get("comprobante"))
        ing = Ingreso(
            fecha=parse_fecha(request.form.get("fecha"), date.today()),
            tipo=request.form["tipo"],
            habitacion_id=habitacion_elegida.id if habitacion_elegida else None,
            inquilino_id=inquilino_elegido.id,
            concepto=request.form.get("concepto", "").strip(),
            monto=monto,
            comprobante=comprobante_nombre,
        )
        db.session.add(ing)
        db.session.commit()
        flash("Ingreso registrado correctamente.", "success")
        return redirect(url_for("ingresos"))

    limite = request.args.get("limite", 40, type=int)
    lista = Ingreso.query.order_by(Ingreso.fecha.desc(), Ingreso.id.desc()).limit(limite).all()
    total_registros = Ingreso.query.count()
    habitaciones_list = Habitacion.query.order_by(Habitacion.nombre).all()
    inquilinos_list = Inquilino.query.filter_by(activo=True).all()
    return render_template(
        "ingresos.html",
        ingresos=lista,
        habitaciones=habitaciones_list,
        inquilinos=inquilinos_list,
        tipos=TIPOS_INGRESO,
        limite=limite,
        total_registros=total_registros,
    )


@app.route("/ingresos/<int:ingreso_id>/eliminar", methods=["POST"])
@login_required
def eliminar_ingreso(ingreso_id):
    ing = Ingreso.query.get_or_404(ingreso_id)
    eliminar_archivo_comprobante(ing.comprobante)
    db.session.delete(ing)
    db.session.commit()
    flash("Ingreso eliminado.", "warning")
    return redirect(url_for("ingresos"))


# --------------------------------------------------------------------------
# Egresos
# --------------------------------------------------------------------------
@app.route("/egresos", methods=["GET", "POST"])
@login_required
def egresos():
    if request.method == "POST":
        if not tipo_valido(request.form.get("tipo"), TIPOS_EGRESO):
            flash("El tipo de egreso no es válido.", "danger")
            return redirect(url_for("egresos"))
        monto = parse_monto(request.form.get("monto"))
        if monto is None or monto <= 0:
            flash("El monto ingresado no es válido.", "danger")
            return redirect(url_for("egresos"))
        comprobante_nombre = guardar_comprobante(request.files.get("comprobante"))
        egr = Egreso(
            fecha=parse_fecha(request.form.get("fecha"), date.today()),
            tipo=request.form["tipo"],
            concepto=request.form.get("concepto", "").strip(),
            monto=monto,
            comprobante=comprobante_nombre,
        )
        db.session.add(egr)
        db.session.commit()
        flash("Egreso registrado correctamente.", "success")
        return redirect(url_for("egresos"))

    limite = request.args.get("limite", 40, type=int)
    lista = Egreso.query.order_by(Egreso.fecha.desc(), Egreso.id.desc()).limit(limite).all()
    total_registros = Egreso.query.count()
    enlaces = EnlacePago.query.order_by(EnlacePago.nombre).all()
    return render_template("egresos.html", egresos=lista, tipos=TIPOS_EGRESO, enlaces=enlaces,
                            limite=limite, total_registros=total_registros)


@app.route("/egresos/<int:egreso_id>/eliminar", methods=["POST"])
@login_required
def eliminar_egreso(egreso_id):
    egr = Egreso.query.get_or_404(egreso_id)
    eliminar_archivo_comprobante(egr.comprobante)
    db.session.delete(egr)
    db.session.commit()
    flash("Egreso eliminado.", "warning")
    return redirect(url_for("egresos"))


# --------------------------------------------------------------------------
# Enlaces de pago en línea (botones hacia los portales de los proveedores)
# --------------------------------------------------------------------------
@app.route("/enlaces_pago", methods=["POST"])
@login_required
def crear_enlace_pago():
    nombre = request.form.get("nombre", "").strip()
    url = request.form.get("url", "").strip()
    if nombre and url:
        db.session.add(EnlacePago(nombre=nombre, url=url))
        db.session.commit()
        flash(f"Enlace de pago '{nombre}' agregado.", "success")
    else:
        flash("Debes indicar un nombre y una URL para el enlace de pago.", "danger")
    return redirect(url_for("egresos"))


@app.route("/enlaces_pago/<int:enlace_id>/eliminar", methods=["POST"])
@login_required
def eliminar_enlace_pago(enlace_id):
    e = EnlacePago.query.get_or_404(enlace_id)
    db.session.delete(e)
    db.session.commit()
    flash(f"Enlace de pago '{e.nombre}' eliminado.", "warning")
    return redirect(url_for("egresos"))


# --------------------------------------------------------------------------
# Histórico (ingresos + egresos combinados, con filtros)
# --------------------------------------------------------------------------
@app.route("/historico")
@login_required
def historico():
    desde = parse_fecha(request.args.get("desde"))
    hasta = parse_fecha(request.args.get("hasta"))
    tipo_mov = request.args.get("tipo_mov", "todos")
    habitacion_id = request.args.get("habitacion_id", type=int)

    movimientos = []
    montos_ingresos = []
    montos_egresos = []

    if tipo_mov in ("todos", "ingresos"):
        q = Ingreso.query
        if desde:
            q = q.filter(Ingreso.fecha >= desde)
        if hasta:
            q = q.filter(Ingreso.fecha <= hasta)
        if habitacion_id:
            q = q.filter(Ingreso.habitacion_id == habitacion_id)
        for i in q.all():
            movimientos.append({
                "fecha": i.fecha,
                "clase": "Ingreso",
                "tipo": dict(TIPOS_INGRESO).get(i.tipo, i.tipo),
                "habitacion": i.habitacion.nombre if i.habitacion else "-",
                "concepto": i.concepto or "-",
                "monto": i.monto,
                "comprobante": i.comprobante,
            })
            montos_ingresos.append(i.monto)

    if tipo_mov in ("todos", "egresos"):
        q = Egreso.query
        if desde:
            q = q.filter(Egreso.fecha >= desde)
        if hasta:
            q = q.filter(Egreso.fecha <= hasta)
        if not habitacion_id:  # los egresos no están ligados a una habitación
            for e in q.all():
                movimientos.append({
                    "fecha": e.fecha,
                    "clase": "Egreso",
                    "tipo": dict(TIPOS_EGRESO).get(e.tipo, e.tipo),
                    "habitacion": "-",
                    "concepto": e.concepto or "-",
                    "monto": -e.monto,
                    "comprobante": e.comprobante,
                })
                montos_egresos.append(e.monto)

    movimientos.sort(key=lambda m: m["fecha"], reverse=True)

    total_periodo = sum(m["monto"] for m in movimientos)
    habitaciones_list = Habitacion.query.order_by(Habitacion.nombre).all()

    return render_template(
        "historico.html",
        movimientos=movimientos,
        total_periodo=total_periodo,
        habitaciones=habitaciones_list,
        stats_ingresos=estadisticas_lista(montos_ingresos),
        stats_egresos=estadisticas_lista(montos_egresos),
        filtros={
            "desde": request.args.get("desde", ""),
            "hasta": request.args.get("hasta", ""),
            "tipo_mov": tipo_mov,
            "habitacion_id": habitacion_id or "",
        },
    )


# --------------------------------------------------------------------------
# Histórico de egresos por tipo, con gráfico de serie temporal
# --------------------------------------------------------------------------
@app.route("/egresos/historico")
@login_required
def historico_egresos():
    tipo = request.args.get("tipo", "todos")
    desde = parse_fecha(request.args.get("desde"))
    hasta = parse_fecha(request.args.get("hasta"))

    q = Egreso.query
    if tipo != "todos":
        q = q.filter(Egreso.tipo == tipo)
    if desde:
        q = q.filter(Egreso.fecha >= desde)
    if hasta:
        q = q.filter(Egreso.fecha <= hasta)
    lista = q.order_by(Egreso.fecha.desc()).all()
    total_filtrado = sum(e.monto for e in lista)

    return render_template(
        "historico_egresos.html",
        egresos=lista,
        total_filtrado=total_filtrado,
        tipos=TIPOS_EGRESO,
        stats=estadisticas_lista([e.monto for e in lista]),
        filtros={"tipo": tipo, "desde": request.args.get("desde", ""), "hasta": request.args.get("hasta", "")},
    )


@app.route("/api/egresos_serie_temporal")
@login_required
def api_egresos_serie_temporal():
    """Serie mensual (últimos 12 meses) de egresos, por tipo o de un tipo específico."""
    tipo = request.args.get("tipo", "todos")

    meses = ultimos_12_meses()
    etiquetas = [f"{m:02d}/{y}" for y, m in meses]

    tipos_a_graficar = TIPOS_EGRESO if tipo == "todos" else [(v, l) for v, l in TIPOS_EGRESO if v == tipo]

    series = []
    for valor_tipo, etiqueta_tipo in tipos_a_graficar:
        valores = []
        for y, m in meses:
            t = total(
                Egreso.query.filter(
                    Egreso.tipo == valor_tipo,
                    extract("year", Egreso.fecha) == y,
                    extract("month", Egreso.fecha) == m,
                ),
                Egreso.monto,
            )
            valores.append(float(round(t, 2)))
        series.append({"nombre": etiqueta_tipo, "valores": valores})

    return jsonify({"etiquetas": etiquetas, "series": series})


# --------------------------------------------------------------------------
# Balance con gráficos
# --------------------------------------------------------------------------
@app.route("/balance")
@login_required
def balance():
    return render_template("balance.html")


@app.route("/api/balance_mensual")
@login_required
def api_balance_mensual():
    """Devuelve ingresos y egresos agrupados por mes (últimos 12 meses), el balance
    de cada mes por separado, y el balance acumulado (suma corriente) del período."""
    meses = ultimos_12_meses()

    etiquetas, ingresos_data, egresos_data, balance_data = [], [], [], []
    for y, m in meses:
        ti = total(
            Ingreso.query.filter(extract("year", Ingreso.fecha) == y,
                                  extract("month", Ingreso.fecha) == m),
            Ingreso.monto,
        )
        te = total(
            Egreso.query.filter(extract("year", Egreso.fecha) == y,
                                 extract("month", Egreso.fecha) == m),
            Egreso.monto,
        )
        etiquetas.append(f"{m:02d}/{y}")
        ingresos_data.append(float(round(ti, 2)))
        egresos_data.append(float(round(te, 2)))
        balance_data.append(float(round(ti - te, 2)))

    balance_acumulado = []
    corriente = 0.0
    for b in balance_data:
        corriente += b
        balance_acumulado.append(round(corriente, 2))

    return jsonify({
        "etiquetas": etiquetas,
        "ingresos": ingresos_data,
        "egresos": egresos_data,
        "balance": balance_data,
        "balance_acumulado": balance_acumulado,
    })


@app.route("/api/ingresos_por_habitacion")
@login_required
def api_ingresos_por_habitacion():
    desde = parse_fecha(request.args.get("desde"))
    hasta = parse_fecha(request.args.get("hasta"))

    habitaciones_list = Habitacion.query.order_by(Habitacion.nombre).all()
    etiquetas, valores = [], []
    for h in habitaciones_list:
        q = Ingreso.query.filter(Ingreso.habitacion_id == h.id)
        if desde:
            q = q.filter(Ingreso.fecha >= desde)
        if hasta:
            q = q.filter(Ingreso.fecha <= hasta)
        etiquetas.append(h.nombre)
        valores.append(float(round(total(q, Ingreso.monto), 2)))

    return jsonify({"etiquetas": etiquetas, "valores": valores})


@app.route("/api/egresos_por_tipo")
@login_required
def api_egresos_por_tipo():
    desde = parse_fecha(request.args.get("desde"))
    hasta = parse_fecha(request.args.get("hasta"))

    q = Egreso.query
    if desde:
        q = q.filter(Egreso.fecha >= desde)
    if hasta:
        q = q.filter(Egreso.fecha <= hasta)

    filas = (
        q.with_entities(Egreso.tipo, func.coalesce(func.sum(Egreso.monto), 0))
        .group_by(Egreso.tipo)
        .all()
    )
    etiquetas_map = dict(TIPOS_EGRESO)
    return jsonify({
        "etiquetas": [etiquetas_map.get(f[0], f[0]) for f in filas],
        "valores": [float(round(f[1], 2)) for f in filas],
    })


# --------------------------------------------------------------------------
# Inicialización de la base de datos
# --------------------------------------------------------------------------
with app.app_context():
    db.create_all()
    if Habitacion.query.count() == 0:
        for n in range(1, 6):
            db.session.add(Habitacion(nombre=f"Habitación {n}", tarifa_mensual=0))
        db.session.commit()

    if EnlacePago.query.count() == 0:
        db.session.add_all([
            EnlacePago(nombre="Agua — Acueducto de Bogotá", url="https://www.acueducto.com.co/"),
            EnlacePago(nombre="Gas — Grupo Vanti", url="https://www.grupovanti.com/"),
            EnlacePago(nombre="Energía — Enel Colombia (Codensa)", url="https://www.enel.com.co/es.html"),
        ])
        db.session.commit()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
