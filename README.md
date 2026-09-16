# RentaAdmin

**RentaAdmin** es una aplicación web para administrar el arriendo de habitaciones
en una casa compartida: inquilinos, ingresos (arriendos, multas, depósitos),
egresos por categoría (agua, gas, energía, internet/TV, impuestos, mantenimiento,
aseo), comprobantes adjuntos, balance mensual y una integración opcional con
herramientas externas de análisis de datos (BI) como Metabase.

Un solo proyecto Flask, sin pasos de compilación de frontend: corre perfecto en
un VPS pequeño (1 vCPU / 1 GB RAM) o en WSL sobre Windows.

**Stack:** Python 3 · Flask · SQLAlchemy · SQLite · Bootstrap 5 · Chart.js

---

## Tabla de contenidos

1. [Características](#características)
2. [Estructura del proyecto](#estructura-del-proyecto)
3. [Requisitos](#requisitos)
4. [Instalación](#instalación)
5. [Configuración (.env)](#configuración-env)
6. [Puesta en producción](#puesta-en-producción-gunicorn--systemd--nginx)
7. [Flujo de despliegue con Git](#flujo-de-despliegue-con-git)
8. [Copias de seguridad](#copias-de-seguridad)
9. [Integración con Metabase (opcional)](#integración-con-metabase-opcional)
10. [Reglas de negocio](#reglas-de-negocio)
11. [Seguridad](#seguridad)
12. [Changelog](#changelog)
13. [Licencia](#licencia)

---

## Características

- **Habitaciones e inquilinos, de forma independiente**: crea inquilinos sin
  asignarlos a una habitación y asígnalos/reubícalos después. Edición completa
  de habitaciones (nombre, tarifa, notas) e inquilinos (nombre, documento,
  teléfono, correo opcional, habitación, estado activo/inactivo).
- **Ingresos**: pagos de arriendo, multas, depósitos u otros, con inquilino
  obligatorio y comprobante adjunto opcional (PDF, JPG o PNG).
- **Egresos por categoría**: Agua, Gas, Energía, Internet/TV Cable, Impuestos,
  Mantenimiento, Aseo, Otro — también con comprobante adjunto opcional.
- **Pagos en línea**: botones configurables hacia los portales de pago de cada
  proveedor de servicios, editables desde la propia interfaz.
- **Histórico** general y por tipo de egreso, con filtros y exportación a PDF
  y CSV (`/historico`, `/egresos/historico`).
- **Balance**: ingresos vs. egresos por mes, ingresos por habitación y egresos
  por categoría filtrables por período (`/balance`), exportable a PDF.
- **Multiusuario con roles**: cuenta administradora (`.env`) y cuentas
  adicionales con rol `admin` o `usuario`; recuperación de contraseña mediante
  pregunta de seguridad.
- **Integración opcional con Metabase** (o cualquier otra herramienta de BI):
  botones configurables que enlazan a dashboards externos conectados
  directamente a la base de datos SQLite de la app.

---

## Estructura del proyecto

```
RentaAdmin/
├── app.py                   # Backend Flask (modelos, rutas, API de gráficos)
├── migrar_bd.py              # Script de migración de base de datos (preserva datos)
├── requirements.txt
├── .env.example               # Plantilla de configuración — copiar como .env
├── .gitignore
├── LICENSE
├── CHANGELOG.md
├── README.md
├── instance/                  # Se crea sola; NO se versiona (datos reales)
│   ├── rentas.db
│   └── comprobantes/
├── templates/                 # Vistas HTML (Jinja2 + Bootstrap 5)
├── static/css/style.css
└── deploy/
    ├── rentas.service         # Servicio systemd (Gunicorn)
    └── nginx_rentas.conf      # Proxy inverso Nginx
```

---

## Requisitos

- Ubuntu 20.04 / 22.04 / 24.04 (funciona igual dentro de WSL2 sobre Windows)
- Python 3.10+
- Acceso `sudo`
- Un dominio o IP pública si se va a exponer a internet (opcional para uso
  local/LAN)

---

## Instalación

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip nginx git ufw

git clone https://github.com/TU_USUARIO/RentaAdmin.git
cd RentaAdmin

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Prueba en modo desarrollo antes de pasar a producción:

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # pega el resultado en SECRET_KEY
nano .env   # define ADMIN_USER / ADMIN_PASSWORD

python app.py
# abre http://localhost:5000
```

La primera vez se crea sola la carpeta `instance/` con la base de datos y las
5 habitaciones de ejemplo. Detén el servidor con `Ctrl+C` cuando confirmes que
funciona.

---

## Configuración (.env)

| Variable | Obligatoria | Descripción |
|---|---|---|
| `SECRET_KEY` | Sí | Clave secreta de Flask (sesiones, CSRF). Genera una con `secrets.token_hex(32)`. |
| `ADMIN_USER` | Sí | Usuario administrador de respaldo (siempre tiene rol admin). |
| `ADMIN_PASSWORD` | Sí | Contraseña del usuario administrador de respaldo. |
| `DATABASE_PATH` | No | Ruta del archivo SQLite. Por defecto `instance/rentas.db`. |
| `METABASE_URL_BALANCE` | No | Enlace al dashboard de Metabase para el botón "Ver balance". Si se deja vacío, el botón no se muestra. |
| `METABASE_URL_INGRESOS` | No | Igual, para el botón de Ingresos. |
| `METABASE_URL_EGRESOS` | No | Igual, para el botón de Egresos. |

---

## Puesta en producción (Gunicorn + systemd + Nginx)

### Permisos

```bash
sudo chown -R www-data:www-data /ruta/a/RentaAdmin
```

### Servicio systemd

Ajusta `deploy/rentas.service` si tu ruta de instalación no es
`/var/www/rentas_app`, luego:

```bash
sudo cp deploy/rentas.service /etc/systemd/system/rentas.service
sudo systemctl daemon-reload
sudo systemctl enable rentas
sudo systemctl start rentas
sudo systemctl status rentas
```

Logs: `sudo journalctl -u rentas -f`

### Nginx como proxy inverso

```bash
sudo cp deploy/nginx_rentas.conf /etc/nginx/sites-available/rentas
sudo nano /etc/nginx/sites-available/rentas   # ajusta server_name
sudo ln -s /etc/nginx/sites-available/rentas /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

### HTTPS gratuito (opcional, con dominio propio)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d tu_dominio.com
```

---

## Flujo de despliegue con Git

Si el servidor es un clon git del repositorio (recomendado), actualizar se
reduce a:

```bash
cd /ruta/a/RentaAdmin
sudo systemctl stop rentas
git pull
pip install -r requirements.txt   # solo si cambiaron las dependencias
python migrar_bd.py               # solo si el esquema de datos cambió (ver CHANGELOG)
sudo systemctl start rentas
```

**Permisos recomendados** para que `git pull` funcione sin `sudo` y Gunicorn
pueda seguir escribiendo en `instance/`:

```bash
sudo chown -R $USER:$USER /ruta/a/RentaAdmin
sudo chown -R www-data:www-data /ruta/a/RentaAdmin/instance
sudo chmod -R g+w /ruta/a/RentaAdmin/instance
sudo chmod g+s /ruta/a/RentaAdmin/instance
sudo usermod -aG www-data $USER   # requiere cerrar y volver a abrir la sesión
```

`migrar_bd.py` crea un respaldo automático con fecha y hora antes de tocar
nada, y es seguro ejecutarlo más de una vez (no duplica cambios).

---

## Copias de seguridad

La base de datos es un único archivo SQLite (`instance/rentas.db`). Los
comprobantes subidos se guardan aparte, en `instance/comprobantes/` —
**respalda ambas cosas**:

```bash
mkdir -p ~/backups
cp instance/rentas.db ~/backups/rentas_$(date +%F).db
tar -czf ~/backups/comprobantes_$(date +%F).tar.gz -C instance comprobantes

# Cron diario a las 2:00 a.m.
crontab -e
0 2 * * * cp /ruta/a/RentaAdmin/instance/rentas.db /home/tu_usuario/backups/rentas_$(date +\%F).db
0 2 * * * tar -czf /home/tu_usuario/backups/comprobantes_$(date +\%F).tar.gz -C /ruta/a/RentaAdmin/instance comprobantes
```

---

## Integración con Metabase (opcional)

RentaAdmin puede mostrar botones que enlazan a dashboards externos de
[Metabase](https://www.metabase.com/) (gratis, de código abierto, con soporte
nativo para SQLite), conectados directamente a `instance/rentas.db`.

### Instalar Metabase (Docker)

```bash
sudo apt install -y docker.io
sudo docker run -d -p 3000:3000 \
  -v /ruta/a/RentaAdmin/instance:/datos-rentas:ro \
  --name metabase metabase/metabase
sudo docker update --restart unless-stopped metabase
```

Entra a `http://localhost:3000`, añade una base de datos tipo **SQLite**
apuntando a `/datos-rentas/rentas.db` (el volumen se monta en modo solo
lectura para no interferir con la app mientras escribe).

### Conectar los botones de RentaAdmin

En tu `.env`, define las URLs de tus dashboards (ver tabla de la
[sección 5](#configuración-env)).

### Ejemplo de consulta SQL — balance mensual

```sql
WITH ingresos_mes AS (
    SELECT strftime('%Y-%m', fecha) AS mes, SUM(monto) AS total_ingresos
    FROM ingresos GROUP BY mes
),
egresos_mes AS (
    SELECT strftime('%Y-%m', fecha) AS mes, SUM(monto) AS total_egresos
    FROM egresos GROUP BY mes
),
meses AS (
    SELECT mes FROM ingresos_mes
    UNION
    SELECT mes FROM egresos_mes
)
SELECT
    m.mes,
    COALESCE(i.total_ingresos, 0) - COALESCE(e.total_egresos, 0) AS balance
FROM meses m
LEFT JOIN ingresos_mes i ON i.mes = m.mes
LEFT JOIN egresos_mes e ON e.mes = m.mes
ORDER BY m.mes;
```

---

## Reglas de negocio

- Un **inquilino** puede existir sin habitación asignada; se le puede asignar
  o reubicar en cualquier momento.
- Una **habitación solo puede tener un inquilino activo a la vez**. La app
  bloquea la asignación (al crear, editar o asignar un inquilino) si la
  habitación de destino ya tiene otro inquilino activo — hay que registrar la
  salida del actual antes de asignar uno nuevo.
- Los **tipos de ingreso/egreso** están restringidos a listas fijas definidas
  en el backend (`TIPOS_INGRESO`, `TIPOS_EGRESO`); no se aceptan valores fuera
  de esas listas, sin importar lo que llegue en la petición.
- Los **montos monetarios** se almacenan como `Numeric(12,2)` (no `float`),
  para evitar errores de redondeo binario, y se validan en el servidor
  (deben ser números positivos), no solo en el HTML del formulario.

---

## Seguridad

RentaAdmin pasó por una revisión de seguridad enfocada en los riesgos típicos
de una aplicación Flask con formularios y sesiones. Medidas implementadas:

- **CSRF**: todos los formularios POST incluyen un token verificado por
  `Flask-WTF` (`CSRFProtect`).
- **Control de acceso por rol**: cuentas `admin` y `usuario`; la gestión de
  usuarios (crear, eliminar, cambiar contraseña o rol) está restringida a
  administradores (`@admin_required`).
- **Sin open redirect**: el parámetro `next` del login se valida contra el
  propio host antes de usarlo en una redirección.
- **Validación server-side**: montos, tipos de movimiento y existencia de
  habitación/inquilino se verifican en el backend, no solo en el navegador.
- **Reglas de integridad de negocio**: no se permiten dos inquilinos activos
  en la misma habitación (ver [sección 10](#reglas-de-negocio)).
- **Contraseñas con hash** (`werkzeug.security`), nunca en texto plano.
- **Comprobantes protegidos**: los archivos subidos se sirven únicamente a
  usuarios autenticados, desde una ruta fuera de `static/`.

Si encuentras un problema de seguridad adicional, abre un issue o revisa
`CHANGELOG.md` para el historial de correcciones.

---

---

## Mantenimiento

Al eliminar un ingreso o egreso, su comprobante adjunto (si tenía) se borra
automáticamente del disco. Para limpiar archivos huérfanos que hayan quedado
de antes de esta protección:

```bash
python limpiar_comprobantes_huerfanos.py            # solo muestra qué borraría
python limpiar_comprobantes_huerfanos.py --borrar   # borra de verdad
```

---

## Changelog

Ver [CHANGELOG.md](CHANGELOG.md) para el historial de versiones y cambios.

---

## Licencia

Este proyecto se distribuye bajo la licencia MIT — ver [LICENSE](LICENSE).
