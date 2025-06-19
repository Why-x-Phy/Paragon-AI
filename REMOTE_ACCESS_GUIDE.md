# Remote Access Guide - Grafana & Prometheus on Cloud Servers

When running Calvin AI on a cloud server, you need special configuration to access Grafana and Prometheus from your local machine.

## 🌐 Access Methods (Choose One)

### **Option 1: Direct Port Access (Easiest)**

#### **1. Update Server IP in Docker Config**
```bash
# Replace YOUR_SERVER_IP in docker-compose.prod.yml with your actual server IP
sed -i 's/YOUR_SERVER_IP/123.456.789.012/g' docker/docker-compose.prod.yml
```

#### **2. Configure Firewall**
```bash
# On Ubuntu/Debian cloud server:
sudo ufw allow 3000/tcp comment "Grafana"
sudo ufw allow 9090/tcp comment "Prometheus"
sudo ufw reload

# Verify rules
sudo ufw status
```

#### **3. Start Monitoring**
```bash
cd docker
docker-compose -f docker-compose.prod.yml --env-file .env.prod --profile monitoring up -d
```

#### **4. Access from Your Browser**
- **Grafana**: `http://YOUR_SERVER_IP:3000`
- **Prometheus**: `http://YOUR_SERVER_IP:9090`

**⚠️ Security Note**: This exposes Grafana to the internet. Use strong passwords!

---

### **Option 2: SSH Tunnel (Most Secure) ⭐ RECOMMENDED**

#### **1. Keep Ports Local Only**
```yaml
# In docker-compose.prod.yml, use:
ports:
  - "127.0.0.1:3000:3000"  # Only localhost access
  - "127.0.0.1:9090:9090"  # Only localhost access
```

#### **2. Create SSH Tunnels**
```bash
# From your LOCAL machine, create tunnels to your cloud server:

# Grafana tunnel
ssh -L 3000:localhost:3000 your_user@YOUR_SERVER_IP -N -f

# Prometheus tunnel  
ssh -L 9090:localhost:9090 your_user@YOUR_SERVER_IP -N -f

# Combined tunnel (one command)
ssh -L 3000:localhost:3000 -L 9090:localhost:9090 your_user@YOUR_SERVER_IP -N -f
```

#### **3. Access Locally**
- **Grafana**: `http://localhost:3000` (tunneled to cloud server)
- **Prometheus**: `http://localhost:9090` (tunneled to cloud server)

#### **4. Close Tunnels When Done**
```bash
# Find and kill SSH tunnel processes
ps aux | grep "ssh -L"
kill <process_id>

# Or close all SSH tunnels
pkill -f "ssh -L"
```

---

### **Option 3: AWS Amplify Domain Setup (Professional) ⭐ PERFECT FOR CABALCALVIN.COM**

Since you're using AWS Amplify with `cabalcalvin.com`, here's the exact setup for monitoring subdomain:

#### **1. Set Up Monitoring Subdomain in AWS Route 53**
```bash
# Log into AWS Console → Route 53 → Hosted Zones → cabalcalvin.com

# Create A Record for monitoring subdomain:
# Record Name: monitoring
# Record Type: A  
# Value: YOUR_CLOUD_SERVER_IP (your Calvin AI server)
# TTL: 300

# This creates: monitoring.cabalcalvin.com → YOUR_SERVER_IP
```

#### **2. Install Nginx + Certbot on Cloud Server**
```bash
# On your Calvin AI cloud server:
sudo apt update
sudo apt install nginx certbot python3-certbot-nginx

# Verify nginx is running
sudo systemctl status nginx
sudo systemctl enable nginx
```

#### **3. Configure Nginx for Grafana + Prometheus**
```bash
# Create nginx config file
sudo nano /etc/nginx/sites-available/calvin-monitoring
```

**Paste this configuration:**
```nginx
# Calvin AI Monitoring - monitoring.cabalcalvin.com
server {
    listen 80;
    server_name monitoring.cabalcalvin.com;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Grafana (main interface)
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        
        # WebSocket support for Grafana
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Prometheus (for advanced users)
    location /prometheus/ {
        proxy_pass http://localhost:9090/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Handle Prometheus console redirects
        proxy_redirect ~^http://[^/]+/(.*) https://$host/$1;
    }

    # Health check endpoint
    location /health {
        access_log off;
        return 200 "Calvin AI Monitoring OK\n";
        add_header Content-Type text/plain;
    }
}
```

#### **4. Enable Site and Get SSL Certificate**
```bash
# Enable the site
sudo ln -s /etc/nginx/sites-available/calvin-monitoring /etc/nginx/sites-enabled/

# Test nginx configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx

# Get free SSL certificate from Let's Encrypt
sudo certbot --nginx -d monitoring.cabalcalvin.com

# Verify auto-renewal is set up
sudo certbot renew --dry-run
```

#### **5. Update Docker Compose for Domain Access**
```bash
# Update your docker-compose.prod.yml
sed -i 's/YOUR_SERVER_IP/monitoring.cabalcalvin.com/g' docker/docker-compose.prod.yml

# Keep ports localhost-only for security (nginx will proxy)
# ports should be:
#   - "127.0.0.1:3000:3000"  # Grafana - localhost only
#   - "127.0.0.1:9090:9090"  # Prometheus - localhost only
```

#### **6. Update Grafana Configuration for Domain**
```bash
# Create grafana environment overrides
cat >> docker/.env.prod << EOF

# Grafana domain configuration
GF_SERVER_ROOT_URL=https://monitoring.cabalcalvin.com
GF_SERVER_DOMAIN=monitoring.cabalcalvin.com
GF_SERVER_ENFORCE_DOMAIN=true
GF_SECURITY_COOKIE_SECURE=true
GF_SECURITY_COOKIE_SAMESITE=strict
EOF
```

#### **7. Start Monitoring Stack**
```bash
cd docker
docker-compose -f docker-compose.prod.yml --env-file .env.prod --profile monitoring up -d

# Verify services are running
docker ps | grep -E "(grafana|prometheus)"
curl -I http://localhost:3000  # Should return 200
```

#### **8. Test Domain Access**
```bash
# Test from your server
curl -I https://monitoring.cabalcalvin.com
curl -I https://monitoring.cabalcalvin.com/prometheus

# Should return 200 OK responses
```

#### **9. Access Your Professional Monitoring**
- **Grafana**: `https://monitoring.cabalcalvin.com`
- **Prometheus**: `https://monitoring.cabalcalvin.com/prometheus`
- **Health Check**: `https://monitoring.cabalcalvin.com/health`

**Login Credentials:**
- Username: `admin`
- Password: `${GRAFANA_PASSWORD}` (from your .env.prod file)

---

### **AWS Amplify Integration Benefits**

#### **🎯 Why This Setup is Perfect for Calvin AI:**

1. **Professional Branding**: `monitoring.cabalcalvin.com` looks professional
2. **SSL Security**: Automatic HTTPS with Let's Encrypt certificates  
3. **Easy Access**: No VPN or tunnels needed for team access
4. **Mobile Friendly**: Access dashboards on mobile devices anywhere
5. **AWS Integration**: Leverages your existing AWS infrastructure

#### **🔒 Security Features Included:**

- **HTTPS Only**: All traffic encrypted with SSL
- **Security Headers**: XSS protection, frame options, content type validation
- **Localhost Backend**: Grafana/Prometheus not exposed directly to internet
- **Domain Validation**: Grafana only responds to correct domain
- **Automatic Renewal**: SSL certificates auto-renew every 90 days

#### **📱 Team Access:**

Your team can now access Calvin AI monitoring at:
- **Desktop**: `https://monitoring.cabalcalvin.com`
- **Mobile**: Same URL works on phones/tablets
- **API Access**: `https://monitoring.cabalcalvin.com/api/` for integrations

#### **🔧 AWS Route 53 Advanced Configuration (Optional):**

```bash
# Set up subdomain with health checks in Route 53:

# Health Check Configuration:
# - Type: HTTPS
# - Domain: monitoring.cabalcalvin.com
# - Path: /health
# - Check Interval: 30 seconds
# - Failure Threshold: 3

# Failover Record (if you have backup server):
# Primary: monitoring.cabalcalvin.com → PRIMARY_SERVER_IP
# Secondary: monitoring.cabalcalvin.com → BACKUP_SERVER_IP
```

#### **💡 Pro Tips for AWS Amplify Users:**

1. **Amplify Console Integration**: 
   - Link to monitoring from your main app: `window.open('https://monitoring.cabalcalvin.com')`

2. **Single Sign-On** (Advanced):
   ```bash
   # Configure Grafana with AWS Cognito for unified auth
   GF_AUTH_GENERIC_OAUTH_ENABLED=true
   GF_AUTH_GENERIC_OAUTH_CLIENT_ID=your_cognito_client_id
   GF_AUTH_GENERIC_OAUTH_AUTH_URL=https://your-domain.auth.region.amazoncognito.com/oauth2/authorize
   ```

3. **CloudWatch Integration**:
   ```bash
   # Add AWS CloudWatch as Grafana data source for AWS metrics
   # This complements your Calvin AI metrics with AWS infrastructure metrics
   ```

---

## 🔒 Security Best Practices

### **Authentication & Access Control**

#### **Grafana Security**
```bash
# Strong admin password in .env.prod
GRAFANA_PASSWORD=Very$ecure!Password123!

# Disable sign-up (already configured)
GF_USERS_ALLOW_SIGN_UP=false

# Enable anonymous access for read-only dashboards (optional)
GF_AUTH_ANONYMOUS_ENABLED=true
GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer
```

#### **Prometheus Security**
```yaml
# Add basic auth to prometheus.yml
global:
  external_labels:
    cluster: 'calvin-ai-prod'

# Add web config file for authentication
web:
  - web.config.file: /etc/prometheus/web.yml
```

#### **Firewall Rules (If Using Direct Access)**
```bash
# Restrict access to specific IPs only
sudo ufw delete allow 3000/tcp
sudo ufw delete allow 9090/tcp

# Allow only your IP
sudo ufw allow from YOUR_HOME_IP to any port 3000
sudo ufw allow from YOUR_HOME_IP to any port 9090

# Allow your office/VPN IP range
sudo ufw allow from 203.0.113.0/24 to any port 3000
sudo ufw allow from 203.0.113.0/24 to any port 9090
```

---

## 🚀 Quick Setup Commands

### **For SSH Tunnel Method (Recommended)**

**On Cloud Server:**
```bash
# 1. Start monitoring stack (localhost only)
cd docker
docker-compose -f docker-compose.prod.yml --env-file .env.prod --profile monitoring up -d

# 2. Verify services are running
docker ps | grep -E "(grafana|prometheus)"
```

**On Your Local Machine:**
```bash
# 3. Create SSH tunnel
ssh -L 3000:localhost:3000 -L 9090:localhost:9090 your_user@YOUR_SERVER_IP -N -f

# 4. Open browser
open http://localhost:3000  # macOS
# or
start http://localhost:3000  # Windows
# or  
xdg-open http://localhost:3000  # Linux
```

### **For Direct Access Method**

**On Cloud Server:**
```bash
# 1. Update server IP in config
sed -i 's/YOUR_SERVER_IP/YOUR_ACTUAL_SERVER_IP/g' docker/docker-compose.prod.yml

# 2. Configure firewall
sudo ufw allow 3000/tcp
sudo ufw allow 9090/tcp

# 3. Start monitoring stack
cd docker
docker-compose -f docker-compose.prod.yml --env-file .env.prod --profile monitoring up -d

# 4. Verify external access
curl -I http://YOUR_SERVER_IP:3000
```

---

## 🔧 Troubleshooting Remote Access

### **Connection Refused**
```bash
# Check if services are running
docker ps | grep -E "(grafana|prometheus)"

# Check port binding
netstat -tlnp | grep -E "(3000|9090)"

# Check firewall status
sudo ufw status

# Check service logs
docker logs calvin-grafana-prod
docker logs calvin-prometheus-prod
```

### **SSH Tunnel Issues**
```bash
# Test SSH connection first
ssh your_user@YOUR_SERVER_IP "echo 'SSH works'"

# Verbose SSH tunnel for debugging
ssh -v -L 3000:localhost:3000 your_user@YOUR_SERVER_IP

# Check if tunnel is active
lsof -i :3000  # On your local machine
```

### **Grafana Login Issues**
```bash
# Reset Grafana admin password
docker exec -it calvin-grafana-prod grafana-cli admin reset-admin-password newpassword

# Check Grafana config
docker exec -it calvin-grafana-prod cat /etc/grafana/grafana.ini | grep -A5 "\[server\]"
```

### **Prometheus Data Issues**
```bash
# Check Prometheus targets
curl http://localhost:9090/api/v1/targets  # Through tunnel

# Check Prometheus config
docker exec -it calvin-prometheus-prod cat /etc/prometheus/prometheus.yml
```

---

## 💡 Pro Tips

### **1. Persistent SSH Tunnels**
```bash
# Use autossh for persistent tunnels that reconnect automatically
sudo apt install autossh  # On your local Linux machine

# Create persistent tunnel
autossh -M 20000 -L 3000:localhost:3000 -L 9090:localhost:9090 your_user@YOUR_SERVER_IP -N
```

### **2. SSH Config for Easy Access**
```bash
# Add to ~/.ssh/config on your local machine
Host calvin-server
    HostName YOUR_SERVER_IP
    User your_user
    LocalForward 3000 localhost:3000
    LocalForward 9090 localhost:9090

# Then just run:
ssh calvin-server -N -f
```

### **3. Mobile Access**
For viewing dashboards on mobile, use the direct access method with strong authentication, or set up a VPN to your cloud server.

### **4. Team Access**
For team access, use the reverse proxy method with proper authentication and SSL certificates.

---

## 📱 Mobile Dashboard Access

### **Grafana Mobile App**
1. Install **Grafana Mobile** app (iOS/Android)
2. Add server: `http://YOUR_SERVER_IP:3000` (or domain)
3. Login with admin credentials
4. Access all dashboards on mobile

### **Web App**
1. Access Grafana via browser on mobile
2. Add to home screen for app-like experience
3. Works with all access methods above

---

Choose the method that best fits your security requirements and technical setup! 🎯 