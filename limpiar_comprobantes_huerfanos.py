#!/usr/bin/env python3
"""
Limpieza de comprobantes huérfanos.

Busca archivos en instance/comprobantes/ que ya no estén referenciados por
ningún Ingreso ni Egreso en la base de datos (por ejemplo, porque el registro
se eliminó antes de que existiera la limpieza automática al borrar).

Por defecto solo MUESTRA qué borraría, sin tocar nada (modo simulación).
Pasa --borrar para eliminarlos de verdad.

USO (con el entorno virtual activado):
    cd /var/www/rentas_app
    source venv/bin/activate
    python limpiar_comprobantes_huerfanos.py            # solo muestra
    python limpiar_comprobantes_huerfanos.py --borrar   # borra de verdad
"""
import os
import sys
import sqlite3

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "instance", "rentas.db"))
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(BASE_DIR, DB_PATH)
COMPROBANTES_DIR = os.path.join(BASE_DIR, "instance", "comprobantes")

modo_borrar = "--borrar" in sys.argv

if not os.path.exists(DB_PATH):
    print(f"No se encontró la base de datos en: {DB_PATH}")
    raise SystemExit(1)

if not os.path.isdir(COMPROBANTES_DIR):
    print("No existe la carpeta de comprobantes; no hay nada que limpiar.")
    raise SystemExit(0)

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

referenciados = set()
for tabla in ("ingresos", "egresos"):
    cur.execute(f"SELECT comprobante FROM {tabla} WHERE comprobante IS NOT NULL")
    referenciados.update(fila[0] for fila in cur.fetchall())
con.close()

archivos_en_disco = set(os.listdir(COMPROBANTES_DIR))
huerfanos = sorted(archivos_en_disco - referenciados)

if not huerfanos:
    print("No se encontraron comprobantes huérfanos. Todo en orden.")
    raise SystemExit(0)

print(f"Se encontraron {len(huerfanos)} archivo(s) huérfano(s):")
for nombre in huerfanos:
    print(" -", nombre)

if modo_borrar:
    for nombre in huerfanos:
        os.remove(os.path.join(COMPROBANTES_DIR, nombre))
    print(f"\nSe borraron los {len(huerfanos)} archivo(s) huérfano(s).")
else:
    print("\nEsto fue solo una simulación — no se borró nada.")
    print("Para borrarlos de verdad, ejecuta: python limpiar_comprobantes_huerfanos.py --borrar")
