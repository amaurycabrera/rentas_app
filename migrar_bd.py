#!/usr/bin/env python3
"""
Script de migración de la base de datos.

Actualiza el esquema de una base de datos ya existente para que sea compatible
con la nueva versión de la app, SIN BORRAR los datos que ya tengas cargados
(habitaciones, inquilinos, ingresos, egresos).

Cambios que aplica (solo si hacen falta):
  1. Agrega la columna 'documento' a la tabla de inquilinos.
  2. Permite que 'habitacion_id' quede vacío en inquilinos (para poder crear
     inquilinos sin asignarlos todavía a una habitación).
  3. Crea la tabla 'usuarios' si no existe (para las cuentas de acceso adicionales).
  4. Agrega la columna 'comprobante' a ingresos y egresos (para adjuntar
     facturas/recibos en PDF, JPG o PNG).
  5. Agrega la columna 'rol' a usuarios (todos los existentes quedan como
     'usuario'; asciende a administrador a los que necesites desde la app).

Antes de tocar nada, crea un respaldo con fecha y hora en la misma carpeta.

USO (con el entorno virtual activado y la app detenida):
    cd /var/www/rentas_app
    source venv/bin/activate
    sudo systemctl stop rentas
    python migrar_bd.py
    sudo systemctl start rentas
"""
import os
import shutil
import sqlite3
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "instance", "rentas.db"))
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(BASE_DIR, DB_PATH)

if not os.path.exists(DB_PATH):
    print(f"No se encontró la base de datos en: {DB_PATH}")
    print("Si es una instalación nueva, no necesitas ejecutar esta migración: "
          "al iniciar la app se creará directamente con el esquema correcto.")
    raise SystemExit(1)

respaldo = DB_PATH + ".respaldo_" + datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(DB_PATH, respaldo)
print(f"Respaldo creado en: {respaldo}")

con = sqlite3.connect(DB_PATH)
cur = con.cursor()


def columnas(tabla):
    cur.execute(f"PRAGMA table_info({tabla})")
    # nombre -> (cid, name, type, notnull, dflt_value, pk)
    return {fila[1]: fila for fila in cur.fetchall()}


cambios = []

# 1. Columna 'documento' en inquilinos
cols = columnas("inquilinos")
if "documento" not in cols:
    cur.execute("ALTER TABLE inquilinos ADD COLUMN documento VARCHAR(40)")
    cambios.append("Se agregó la columna 'documento' a inquilinos.")
    cols = columnas("inquilinos")

# 2. Permitir habitacion_id NULL en inquilinos
if cols["habitacion_id"][3] == 1:  # notnull == 1 -> hay que reconstruir la tabla
    cur.execute("""
        CREATE TABLE inquilinos_nueva (
            id INTEGER PRIMARY KEY,
            nombre VARCHAR(120) NOT NULL,
            documento VARCHAR(40),
            telefono VARCHAR(40),
            email VARCHAR(120),
            habitacion_id INTEGER,
            fecha_ingreso DATE,
            fecha_salida DATE,
            activo BOOLEAN,
            FOREIGN KEY(habitacion_id) REFERENCES habitaciones(id)
        )
    """)
    cur.execute("""
        INSERT INTO inquilinos_nueva
            (id, nombre, documento, telefono, email, habitacion_id, fecha_ingreso, fecha_salida, activo)
        SELECT id, nombre, documento, telefono, email, habitacion_id, fecha_ingreso, fecha_salida, activo
        FROM inquilinos
    """)
    cur.execute("DROP TABLE inquilinos")
    cur.execute("ALTER TABLE inquilinos_nueva RENAME TO inquilinos")
    cambios.append("Se permitió que 'habitacion_id' quede vacío en inquilinos.")

# 3. Tabla 'usuarios'
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='usuarios'")
if not cur.fetchone():
    cur.execute("""
        CREATE TABLE usuarios (
            id INTEGER PRIMARY KEY,
            nombre_usuario VARCHAR(80) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            pregunta_seguridad VARCHAR(255) NOT NULL,
            respuesta_hash VARCHAR(255) NOT NULL,
            rol VARCHAR(20) NOT NULL DEFAULT 'usuario',
            creado_en DATETIME
        )
    """)
    cambios.append("Se creó la tabla 'usuarios' (con columna 'rol').")
else:
    cols_usuarios = columnas("usuarios")
    if "rol" not in cols_usuarios:
        cur.execute("ALTER TABLE usuarios ADD COLUMN rol VARCHAR(20) NOT NULL DEFAULT 'usuario'")
        cambios.append("Se agregó la columna 'rol' a usuarios (todos los existentes quedaron como 'usuario'; "
                        "asciende a administrador a los que necesites desde la sección Usuarios).")

# 4. Columna 'comprobante' en ingresos y egresos
cols_ingresos = columnas("ingresos")
if "comprobante" not in cols_ingresos:
    cur.execute("ALTER TABLE ingresos ADD COLUMN comprobante VARCHAR(255)")
    cambios.append("Se agregó la columna 'comprobante' a ingresos.")

cols_egresos = columnas("egresos")
if "comprobante" not in cols_egresos:
    cur.execute("ALTER TABLE egresos ADD COLUMN comprobante VARCHAR(255)")
    cambios.append("Se agregó la columna 'comprobante' a egresos.")

con.commit()
con.close()

print()
if cambios:
    print("Migración completada:")
    for c in cambios:
        print(" -", c)
    print()
    print("Nota: los egresos ya registrados con el tipo antiguo 'Servicios públicos' "
          "conservan ese valor internamente. Si quieres reclasificarlos en Agua, Gas, "
          "Energía o Internet/TV, deberás eliminarlos y volver a registrarlos con el "
          "nuevo tipo (son pocos registros, dado que la app se desplegó recientemente).")
else:
    print("La base de datos ya estaba actualizada; no se hicieron cambios.")
