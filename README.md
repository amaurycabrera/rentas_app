# RentaAdmin

Aplicación web para administrar el arriendo de habitaciones, controlar ingresos y egresos, gestionar inquilinos y consultar históricos y balances.

Está desarrollada con **Python + Flask + SQLite** y puede ejecutarse en un servidor Ubuntu pequeño mediante **Gunicorn + systemd + Nginx**.

## Funcionalidades

* Gestión de habitaciones e inquilinos.
* Creación de inquilinos sin habitación y posterior asignación o reubicación.
* Registro de ingresos:

  * Arriendos.
  * Multas.
  * Depósitos o garantías.
  * Otros ingresos.
* Registro de egresos:

  * Agua.
  * Gas.
  * Energía.
  * Internet/TV.
  * Impuestos.
  * Mantenimiento.
  * Aseo.
  * Otros.
* Asociación de movimientos con habitación e inquilino.
* Histórico general con filtros por fecha, tipo y habitación.
* Histórico de egresos por categoría.
* Balance mensual y acumulado.
* Gráficos de ingresos y egresos.
* Exportación de información a **PDF y CSV**.
* Carga de comprobantes en **PDF, JPG, JPEG y PNG**, con límite de 10 MB.
* Gestión de usuarios con roles `admin` y `usuario`.
* Recuperación de contraseña mediante pregunta de seguridad para usuarios registrados.
* Enlaces opcionales a dashboards externos, como Metabase.

## Tecnologías

### Backend

* Python 3
* Flask 3
* Flask-SQLAlchemy
* Flask-WTF
* SQLite
* Werkzeug
* python-dotenv
* ReportLab

### Frontend

* HTML / Jinja2
* Bootstrap 5
* JavaScript
* Chart.js

### Producción

* Gunicorn
* systemd
* Nginx
* Ubuntu

Las dependencias Python están definidas en `requirements.txt`.

## Configuración

Copiar el archivo de ejemplo:

```bash
cp .env.example .env
```

Configurar:

```env
SECRET_KEY=una-clave-larga-y-aleatoria
ADMIN_USER=admin
ADMIN_PASSWORD=una-contraseña-segura
DATABASE_PATH=instance/rentas.db
```

`DATABASE_PATH` permite definir la ubicación de la base de datos SQLite.

Para generar una clave segura:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

No subir `.env` al repositorio.

## Instalación local

```bash
git clone <repositorio>
cd rentas_app

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Ejecutar:

```bash
python app.py
```

La aplicación utiliza SQLite y crea automáticamente el directorio `instance/` y el directorio destinado a comprobantes cuando son necesarios.

## Seguridad

La aplicación incorpora:

* Protección CSRF mediante Flask-WTF.
* Contraseñas almacenadas mediante hash.
* Respuestas de seguridad almacenadas mediante hash.
* Control de acceso mediante sesión.
* Separación de permisos entre `admin` y `usuario`.
* Validación de archivos subidos.
* Nombres de archivo seguros.
* Límite máximo de 10 MB por archivo.
* Validación de redirecciones posteriores al inicio de sesión.

## Base de datos

La aplicación utiliza una base de datos SQLite:

```text
instance/rentas.db
```

Los comprobantes se almacenan en:

```text
instance/comprobantes/
```

Los comprobantes permitidos son:

```text
PDF
JPG
JPEG
PNG
```

Por seguridad y para mantener la información completa, los respaldos deben incluir **la base de datos y la carpeta de comprobantes**.

## Producción en Ubuntu

Para una instalación de producción se puede utilizar:

```text
Nginx
   ↓
Gunicorn
   ↓
Flask
   ↓
SQLite
```

El proyecto incluye archivos de despliegue:

```text
deploy/
├── rentas.service
└── nginx_rentas.conf
```

Instalación básica:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git ufw
```

Crear el entorno virtual:

```bash
cd /var/www/rentas_app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Activar el servicio:

```bash
sudo cp deploy/rentas.service /etc/systemd/system/rentas.service
sudo systemctl daemon-reload
sudo systemctl enable rentas
sudo systemctl start rentas
```

Comprobar:

```bash
sudo systemctl status rentas
```

Logs:

```bash
sudo journalctl -u rentas -f
```

Configurar Nginx:

```bash
sudo cp deploy/nginx_rentas.conf /etc/nginx/sites-available/rentas
sudo ln -s /etc/nginx/sites-available/rentas /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

Para una instalación expuesta a Internet se recomienda utilizar HTTPS.

## Actualización

Antes de actualizar, realizar un respaldo de:

```text
instance/rentas.db
instance/comprobantes/
```

Después:

```bash
cd /var/www/rentas_app

git pull origin main

source venv/bin/activate
pip install -r requirements.txt

sudo systemctl restart rentas
```

Si una versión requiere cambios en la estructura de la base de datos:

```bash
python migrar_bd.py
```

## Integración con Metabase

La aplicación permite configurar enlaces opcionales hacia dashboards externos.

Variables disponibles:

```env
METABASE_URL_BALANCE=
METABASE_URL_INGRESOS=
METABASE_URL_EGRESOS=
```

Si no se configuran, los botones correspondientes no se muestran.

Los históricos también pueden exportarse a CSV para utilizarlos posteriormente en herramientas de análisis.

## Estructura principal

```text
rentas_app/
├── app.py
├── migrar_bd.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── instance/
│   ├── rentas.db
│   └── comprobantes/
├── static/
├── templates/
└── deploy/
    ├── rentas.service
    └── nginx_rentas.conf
```

## Mantenimiento

Tareas recomendadas:

* Mantener actualizado el sistema operativo.
* Mantener las dependencias Python actualizadas cuando corresponda.
* Realizar copias de seguridad periódicas.
* No publicar `.env`.
* No almacenar credenciales directamente en el código.
* Verificar periódicamente el estado del servicio:

```bash
sudo systemctl status rentas
```

## Estado del proyecto

Proyecto funcional orientado a la administración de una propiedad con habitaciones en alquiler.

La arquitectura está preparada para continuar incorporando nuevas funcionalidades sin modificar la estructura principal de despliegue.
