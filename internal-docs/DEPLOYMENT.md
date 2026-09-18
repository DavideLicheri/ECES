# 🚀 Deployment Guide

Guida completa per il deployment del sistema EURING in produzione.

## 🎯 Opzioni di Deployment

### **1. Docker (Consigliato)**
- **Isolamento** completo dell'ambiente
- **Scalabilità** orizzontale
- **Gestione** semplificata delle dipendenze
- **Portabilità** tra ambienti

### **2. Server Tradizionale**
- **Controllo** completo del sistema
- **Performance** ottimizzate
- **Integrazione** con infrastruttura esistente

### **3. Cloud Platforms**
- **AWS/Azure/GCP** per scalabilità
- **Heroku/Vercel** per semplicità
- **GitHub Pages** per frontend statico

## 🐳 Deployment Docker

### **Dockerfile Backend**
```dockerfile
FROM python:3.9-slim

WORKDIR /app

# Installa dipendenze
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia codice
COPY . .

# Espone porta
EXPOSE 8000

# Comando di avvio
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### **Dockerfile Frontend**
```dockerfile
FROM node:18-alpine as build

WORKDIR /app

# Installa dipendenze
COPY package*.json ./
RUN npm ci --only=production

# Build applicazione
COPY . .
RUN npm run build

# Serve con nginx
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### **docker-compose.yml**
```yaml
version: '3.8'

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - PYTHONPATH=/app
    volumes:
      - ./backend/data:/app/data
    restart: unless-stopped

  frontend:
    build: ./frontend
    ports:
      - "80:80"
    depends_on:
      - backend
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - frontend
      - backend
    restart: unless-stopped
```

### **Comandi Docker**
```bash
# Build e avvio
docker-compose up -d --build

# Logs
docker-compose logs -f

# Stop
docker-compose down

# Update
docker-compose pull
docker-compose up -d --build
```

## 🖥️ Server Tradizionale

### **Requisiti Sistema**
- **OS**: Ubuntu 20.04+ / CentOS 8+ / Debian 11+
- **RAM**: 2GB minimo, 4GB consigliato
- **CPU**: 2 core minimo
- **Storage**: 10GB per applicazione + dati
- **Network**: Porta 80/443 aperta

### **Setup Backend**
```bash
# Installa Python 3.9+
sudo apt update
sudo apt install python3.9 python3.9-pip python3.9-venv

# Crea ambiente virtuale
python3.9 -m venv /opt/euring-backend
source /opt/euring-backend/bin/activate

# Installa dipendenze
cd /opt/euring-system/backend
pip install -r requirements.txt

# Crea servizio systemd
sudo tee /etc/systemd/system/euring-backend.service > /dev/null <<EOF
[Unit]
Description=EURING Backend API
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/euring-system/backend
Environment=PATH=/opt/euring-backend/bin
Environment=PYTHONPATH=/opt/euring-system/backend
ExecStart=/opt/euring-backend/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Avvia servizio
sudo systemctl daemon-reload
sudo systemctl enable euring-backend
sudo systemctl start euring-backend
```

### **Setup Frontend**
```bash
# Installa Node.js 18+
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# Build frontend
cd /opt/euring-system/frontend
npm install
npm run build

# Copia file statici
sudo cp -r dist/* /var/www/html/euring/

# Configura nginx
sudo tee /etc/nginx/sites-available/euring > /dev/null <<EOF
server {
    listen 80;
    server_name your-domain.com;
    root /var/www/html/euring;
    index index.html;

    # Frontend
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # API Proxy
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

# Attiva sito
sudo ln -s /etc/nginx/sites-available/euring /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## ☁️ Cloud Deployment

### **AWS (Amazon Web Services)**

#### **EC2 + RDS**
```bash
# Launch EC2 instance (t3.medium)
aws ec2 run-instances \
  --image-id ami-0c02fb55956c7d316 \
  --instance-type t3.medium \
  --key-name your-key \
  --security-group-ids sg-xxxxxxxxx

# Setup come server tradizionale
# RDS per database (se necessario)
```

#### **ECS (Container Service)**
```yaml
# task-definition.json
{
  "family": "euring-system",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "containerDefinitions": [
    {
      "name": "backend",
      "image": "your-account.dkr.ecr.region.amazonaws.com/euring-backend:latest",
      "portMappings": [{"containerPort": 8000}]
    },
    {
      "name": "frontend", 
      "image": "your-account.dkr.ecr.region.amazonaws.com/euring-frontend:latest",
      "portMappings": [{"containerPort": 80}]
    }
  ]
}
```

### **Heroku**
```bash
# Backend
cd backend
echo "web: uvicorn main:app --host 0.0.0.0 --port \$PORT" > Procfile
git init
heroku create euring-backend
git add .
git commit -m "Initial commit"
git push heroku main

# Frontend
cd frontend
npm run build
# Deploy dist/ to static hosting
```

### **Vercel (Frontend)**
```json
// vercel.json
{
  "builds": [
    {
      "src": "package.json",
      "use": "@vercel/static-build",
      "config": { "distDir": "dist" }
    }
  ],
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "https://your-backend.herokuapp.com/api/$1"
    },
    {
      "src": "/(.*)",
      "dest": "/index.html"
    }
  ]
}
```

## 🔒 SSL/HTTPS Setup

### **Let's Encrypt (Gratuito)**
```bash
# Installa certbot
sudo apt install certbot python3-certbot-nginx

# Ottieni certificato
sudo certbot --nginx -d your-domain.com

# Auto-renewal
sudo crontab -e
# Aggiungi: 0 12 * * * /usr/bin/certbot renew --quiet
```

### **Configurazione Nginx HTTPS**
```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    
    # SSL Security
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512;
    ssl_prefer_server_ciphers off;
    
    # HSTS
    add_header Strict-Transport-Security "max-age=63072000" always;
    
    # Frontend
    location / {
        root /var/www/html/euring;
        try_files $uri $uri/ /index.html;
        
        # Cache static assets
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }
    
    # API
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # CORS headers
        add_header Access-Control-Allow-Origin *;
        add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS";
        add_header Access-Control-Allow-Headers "Content-Type, Authorization";
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}
```

## 📊 Monitoring e Logging

### **Backend Logging**
```python
# logging_config.py
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/euring/backend.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
```

### **Nginx Access Logs**
```nginx
# nginx.conf
http {
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                   '$status $body_bytes_sent "$http_referer" '
                   '"$http_user_agent" "$http_x_forwarded_for"';
    
    access_log /var/log/nginx/euring_access.log main;
    error_log /var/log/nginx/euring_error.log;
}
```

### **Health Checks**
```bash
# Script di monitoraggio
#!/bin/bash
# health_check.sh

# Check backend
if curl -f http://localhost:8000/api/euring/health > /dev/null 2>&1; then
    echo "Backend: OK"
else
    echo "Backend: FAIL"
    systemctl restart euring-backend
fi

# Check frontend
if curl -f http://localhost/ > /dev/null 2>&1; then
    echo "Frontend: OK"
else
    echo "Frontend: FAIL"
    systemctl reload nginx
fi
```

## 🔧 Configurazione Produzione

### **Environment Variables**
```bash
# Backend
export PYTHONPATH=/opt/euring-system/backend
export EURING_ENV=production
export EURING_LOG_LEVEL=INFO
export EURING_CORS_ORIGINS=https://your-domain.com

# Frontend
export VITE_API_BASE_URL=https://your-domain.com/api
export VITE_ENV=production
```

### **Performance Tuning**

#### **Backend (FastAPI)**
```python
# main.py
app = FastAPI(
    title="EURING System",
    docs_url="/docs" if os.getenv("EURING_ENV") != "production" else None,
    redoc_url="/redoc" if os.getenv("EURING_ENV") != "production" else None
)

# Gunicorn per produzione
# gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

#### **Frontend (Nginx)**
```nginx
# Compressione
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_types text/plain text/css text/xml text/javascript application/javascript application/xml+rss application/json;

# Cache
location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}
```

## 🔄 CI/CD Pipeline

### **GitHub Actions**
```yaml
# .github/workflows/deploy.yml
name: Deploy EURING System

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '18'
          
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'
          
      - name: Build Frontend
        run: |
          cd frontend
          npm ci
          npm run build
          
      - name: Test Backend
        run: |
          cd backend
          pip install -r requirements.txt
          pytest
          
      - name: Deploy to Server
        run: |
          # SSH deploy script
          ssh user@server 'cd /opt/euring-system && git pull && ./deploy.sh'
```

## 📋 Checklist Deployment

### **Pre-Deployment**
- [ ] **Test completi** passati
- [ ] **Build** frontend senza errori
- [ ] **Dipendenze** aggiornate
- [ ] **Configurazione** produzione verificata
- [ ] **SSL** certificati validi
- [ ] **Backup** dati esistenti

### **Post-Deployment**
- [ ] **Health check** API funzionante
- [ ] **Frontend** carica correttamente
- [ ] **HTTPS** redirect attivo
- [ ] **Logs** senza errori critici
- [ ] **Performance** accettabili
- [ ] **Monitoring** attivo

## 🐛 Troubleshooting

### **Problemi Comuni**

**Backend non risponde:**
```bash
# Check processo
ps aux | grep uvicorn
systemctl status euring-backend

# Check logs
tail -f /var/log/euring/backend.log
journalctl -u euring-backend -f
```

**Frontend non carica:**
```bash
# Check nginx
nginx -t
systemctl status nginx

# Check file
ls -la /var/www/html/euring/
```

**CORS Errors:**
```python
# Verifica configurazione CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-domain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

**Sistema EURING pronto per la produzione! 🚀**