# Despliegue: GitHub → ZimaOS

```
 rama de trabajo ──PR──► main ──► GitHub Actions: pruebas + imagen ──► ghcr.io/<usuario>/panel-cocina:latest
                                                                              │
                                    Portainer en ZimaOS (sondea el repo) ◄────┘  y vuelve a desplegar
```

Nadie entra en el servidor para desplegar: se trabaja en ramas, se fusiona a `main` y Portainer se actualiza solo.

## Ramas

- `main` es lo que está en la tablet. No se trabaja directamente en ella.
- Cada cambio, en su rama (`feature/…`, o `claude/…` si la crea Claude Code) con su pull request.
- Las pruebas se ejecutan en cada push y en cada PR; la imagen solo se construye al fusionar en `main`.
- Recomendado: en GitHub → Settings → Branches, protege `main` y exige que pasen las pruebas antes de fusionar.

## Una sola vez

### 1. Configuración en el servidor

Por SSH en ZimaOS (o con el gestor de archivos):

```sh
mkdir -p /DATA/AppData/panel-cocina/config
# copia ahí config/config.example.yaml como config.yaml y ajústalo
```

### 2. La imagen

Al primer push a `main`, GitHub Actions publica `ghcr.io/<usuario>/panel-cocina`. Si el repositorio es privado,
la imagen también: o la haces pública (GitHub → tu perfil → Packages → panel-cocina → Package settings →
Change visibility; no lleva secretos), o añades en Portainer el registro `ghcr.io` con tu usuario y un token con
permiso `read:packages`.

### 3. El stack en Portainer

Stacks → **Add stack** → **Repository**:

- Repository URL: `https://github.com/<usuario>/panel-cocina`
- Reference: `refs/heads/main`
- Compose path: `deploy/portainer-compose.yml`
- Si el repositorio es privado: **Authentication** con tu usuario y un token de GitHub de solo lectura
  (fine-grained, solo este repositorio, permiso *Contents: Read*).
- **Environment variables:** `IMAGEN=ghcr.io/<usuario>/panel-cocina:latest`, `HA_TOKEN`, `PANEL_TOKEN`, `PANEL_PORT=8090`.
- **GitOps updates:** activado, **Polling** cada 5 minutos, con **Re-pull image** activado.

«Re-pull image» es importante: la imagen siempre se llama `latest`, así que sin él Portainer solo redesplegaría
cuando cambie el compose, no cuando haya imagen nueva.

## Sin Portainer

Con la app de ZimaOS (App Store → «+» → Instalar app personalizada) importando `deploy/portainer-compose.yml`
con las variables puestas a mano. Para actualizar: botón de actualizar la app, o por SSH
`docker compose pull && docker compose up -d`.

## Comprobar

- `http://<ip-de-zimaos>:8090/api/salud`: qué fuente funciona y cuál no.
- En Portainer → Containers → panel-cocina → Logs.
