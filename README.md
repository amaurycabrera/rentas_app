# Administración de Arriendos — Casa de 5 habitaciones

Aplicación web para gestionar el arriendo de habitaciones: ingresos (arriendos, multas,
depósitos), egresos (servicios públicos, impuestos, mantenimiento), histórico de
movimientos y balances con gráficos interactivos.

**Stack:** Python 3 + Flask + SQLAlchemy + SQLite + Bootstrap 5 + Chart.js.
Un solo proyecto, sin pasos de compilación de frontend: ideal para un servidor Ubuntu
pequeño (funciona perfecto en un VPS de 1 vCPU / 1 GB RAM).

---

## 1. Funcionalidades

- **Habitaciones e inquilinos, de forma independiente**: puedes crear inquilinos sin
  asignarlos a una habitación, y asignarlos/reubicarlos más adelante. También se pueden
  **editar** habitaciones e inquilinos (nombre, tarifa, documento, teléfono, correo —ahora
  opcional—, habitación, estado activo/inactivo).
- **Ingresos**: registro de pagos de arriendo, multas, depósitos u otros ingresos,
  asociados opcionalmente a una habitación/inquilino.
- **Egresos por categoría detallada**: Agua, Gas, Energía, Internet/TV Cable, Impuestos,
  Mantenimiento, Aseo, Otro.
- **Histórico general**: todos los movimientos combinados, filtrable por fecha, tipo y
  habitación, exportable a PDF.
- **Histórico de egresos por tipo**: filtro dedicado por categoría de egreso, con
  gráfico de serie temporal (línea) de los últimos 12 meses, exportable a PDF.
- **Balance con gráficos**: ingresos vs. egresos de los últimos 12 meses, balance
  mensual acumulado, ingresos por habitación y egresos por categoría, exportable a PDF.
- **Múltiples usuarios de acceso**: además del usuario administrador definido en `.env`,
  se pueden crear cuentas adicionales desde la sección "Usuarios", cada una con su
  propia contraseña y pregunta de seguridad para **recuperar la contraseña** si se
  olvida (sin necesidad de correo/SMTP).

---

## 2. Requisitos en el servidor Ubuntu

- Ubuntu 20.04 / 22.04 / 24.04
- Acceso `sudo`
- Un dominio o IP pública si se va a exponer a internet (opcional para uso local/LAN)

---

## 3. Instalación paso a paso

### 3.1 Actualizar el sistema e instalar dependencias base

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip nginx git ufw
```

### 3.2 Copiar el proyecto al servidor

Sube la carpeta `rentas_app` (por ejemplo con `scp` o `git`) a `/var/www/rentas_app`:

```bash
sudo mkdir -p /var/www/rentas_app
sudo chown $USER:$USER /var/www/rentas_app
# desde tu máquina local:
scp -r rentas_app/* usuario@TU_SERVIDOR:/var/www/rentas_app/
```

### 3.3 Crear entorno virtual e instalar dependencias Python

```bash
cd /var/www/rentas_app
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.4 Configurar variables de entorno

```bash
cp .env.example .env
nano .env
```

Define al menos:

```
SECRET_KEY=una-clave-larga-y-aleatoria
ADMIN_USER=admin
ADMIN_PASSWORD=una-contraseña-segura
DATABASE_PATH=instance/rentas.db
```

> Genera una `SECRET_KEY` segura con: `python3 -c "import secrets; print(secrets.token_hex(32))"`

### 3.5 Probar en modo desarrollo (opcional, antes de exponerlo)

```bash
source venv/bin/activate
python app.py
```

Abre `http://IP_DEL_SERVIDOR:5000` en tu navegador. Detén con `Ctrl+C` cuando confirmes
que funciona, antes de pasar a producción con Gunicorn.

---

## 4. Puesta en producción con Gunicorn + systemd

### 4.1 Ajustar permisos

```bash
sudo chown -R www-data:www-data /var/www/rentas_app
```

### 4.2 Instalar el servicio systemd

El archivo `deploy/rentas.service` ya está preparado. Cópialo y actívalo:

```bash
sudo cp /var/www/rentas_app/deploy/rentas.service /etc/systemd/system/rentas.service
sudo systemctl daemon-reload
sudo systemctl enable rentas
sudo systemctl start rentas
sudo systemctl status rentas
```

Si necesitas revisar logs:

```bash
sudo journalctl -u rentas -f
```

---

## 5. Nginx como proxy inverso (para servir en el puerto 80/443)

### 5.1 Configurar el sitio

```bash
sudo cp /var/www/rentas_app/deploy/nginx_rentas.conf /etc/nginx/sites-available/rentas
sudo nano /etc/nginx/sites-available/rentas   # reemplaza "tu_dominio_o_ip"
sudo ln -s /etc/nginx/sites-available/rentas /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 5.2 Firewall básico

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Ahora la aplicación queda accesible en `http://tu_dominio_o_ip/`.

### 5.3 (Recomendado) HTTPS gratuito con Let's Encrypt

Si tienes un dominio apuntando al servidor:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d tu_dominio.com
```

Certbot configura el certificado y renueva automáticamente.

---

## 6. Copias de seguridad

La base de datos es un único archivo SQLite: `instance/rentas.db`. Los comprobantes
(facturas/recibos en PDF, JPG o PNG) que se suban desde Ingresos o Egresos se
guardan aparte, en `instance/comprobantes/` — **respalda ambas cosas**, no solo
el archivo `.db`:

```bash
# Copia manual (base de datos + comprobantes)
mkdir -p ~/backups
cp /var/www/rentas_app/instance/rentas.db ~/backups/rentas_$(date +%F).db
tar -czf ~/backups/comprobantes_$(date +%F).tar.gz -C /var/www/rentas_app/instance comprobantes

# Tarea programada (cron) - respaldo diario a las 2:00 a.m.
crontab -e
# agregar las líneas:
0 2 * * * cp /var/www/rentas_app/instance/rentas.db /home/tu_usuario/backups/rentas_$(date +\%F).db
0 2 * * * tar -czf /home/tu_usuario/backups/comprobantes_$(date +\%F).tar.gz -C /var/www/rentas_app/instance comprobantes
```

---

## 7. Actualizar la aplicación

```bash
sudo systemctl stop rentas
# reemplaza los archivos actualizados en /var/www/rentas_app (excepto instance/ y .env)
```

**Si el esquema de la base de datos cambió** (por ejemplo, al pasar de una versión
anterior que no tenía el campo "documento" o la tabla de usuarios), ejecuta el script
de migración antes de volver a iniciar el servicio — no borra ningún dato, y crea un
respaldo automático con fecha y hora antes de tocar nada:

```bash
source venv/bin/activate
python migrar_bd.py
```

Si agregaste alguna librería nueva a `requirements.txt` (por ejemplo `reportlab` para
exportar PDF), instala las dependencias antes de reiniciar:

```bash
pip install -r requirements.txt
```

Finalmente:

```bash
sudo chown -R www-data:www-data /var/www/rentas_app
sudo systemctl start rentas
sudo systemctl status rentas
```

---

## 8. Estructura del proyecto

```
rentas_app/
├── app.py                  # Backend Flask (modelos, rutas, API de gráficos)
├── requirements.txt
├── .env.example
├── instance/                # Se crea sola; contiene rentas.db (SQLite)
├── templates/                # Vistas HTML (Jinja2 + Bootstrap 5)
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── habitaciones.html
│   ├── ingresos.html
│   ├── egresos.html
│   ├── historico.html
│   └── balance.html
├── static/css/style.css
└── deploy/
    ├── rentas.service       # Servicio systemd (Gunicorn)
    └── nginx_rentas.conf    # Proxy inverso Nginx
```

---

## 9. Notas y posibles mejoras futuras

- La base de datos es SQLite, suficiente para este volumen de datos (una casa de 5
  habitaciones). Si en el futuro se necesita alta concurrencia, se puede migrar a
  PostgreSQL cambiando solo `SQLALCHEMY_DATABASE_URI`.
- Se pueden agregar recordatorios automáticos de pago (por correo) con una tarea
  programada (`cron` + `smtplib`), si lo necesitas más adelante.

## 10. Conectar la información a una herramienta de análisis de datos (gratis)

Histórico e Histórico de egresos tienen botón de exportación a **CSV** (además del
PDF), lo que abre dos caminos gratuitos para análisis más avanzado:

### Opción A — Sin instalar nada: Google Sheets + Looker Studio
1. Exporta el CSV que necesites desde la app (Histórico o Histórico de egresos).
2. Súbelo a una hoja de Google Sheets.
3. Conecta [Looker Studio](https://lookerstudio.google.com) (gratis) a esa hoja
   para armar tableros y gráficos personalizados.
4. Repite el proceso cuando quieras datos más recientes (no hay conexión en vivo).

### Opción B — Recomendada: Metabase (gratis, de código abierto, autoalojado)
Metabase tiene soporte **oficial y nativo para SQLite** (se conecta directo al
archivo `rentas.db`, sin necesidad de plugins), y arma dashboards interactivos
en minutos. Instalación con Docker en tu mismo servidor Ubuntu:

```bash
sudo apt install -y docker.io
sudo docker run -d -p 3000:3000 \
  -v /var/www/rentas_app/instance:/datos-rentas:ro \
  --name metabase metabase/metabase
```

Luego entra a `http://TU_IP:3000`, sigue el asistente inicial, y en
"Añadir una base de datos" elige **SQLite**, apuntando al archivo
`/datos-rentas/rentas.db` (la ruta dentro del contenedor, gracias al volumen
montado en modo solo lectura `:ro`, para no interferir con la app mientras escribe).

Con esto puedes construir tus propios tableros: ingresos por habitación en el
tiempo, comparativos de egresos por proveedor, proyecciones, etc. — sin tocar
el código de la app.

