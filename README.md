# Quantlabs-LY-KY-Q

**Quantlabs LY-KY-Q · v0.1.1**

Motor local de señales para los mercados "Bitcoin Up or Down" de 5 minutos, con dashboard en React.
Solo paper trading: no envía órdenes reales.

## Arquitectura

```
yfinance (1m) ─┐
               ├─► laya_mlx_engine.py ──► server.py (FastAPI + WebSocket) ──► Dashboard React
Polymarket ────┘    GAN condicional (MLX)      /ws  /api/state  /api/trades      reloj 5m, modelo vs mercado,
(Gamma + CLOB)      Agente Q (MLX, γ=0)        /api/config                       Kelly, bitácora
                    Kelly binario
                    LayaGate (opcional, laya-mlx)
```

**Qué hace laya-mlx aquí.** `laya-mlx` es un runtime de decisiones tipadas (choice / score / noul)
sobre un encoder bidireccional; no trae GAN ni RL. Por eso la GAN y el agente Q están
implementados directamente en MLX dentro de `laya_mlx_engine.py`, y Laya participa como
compuerta de veto opcional (`LayaGate`): solo puede convertir una compra en "esperar".

**Cómo se calcula P(Up).** Polymarket resuelve Up si el precio al cierre de la vela es ≥ el precio de
apertura. El motor toma el precio actual, el precio a superar y los minutos restantes, y la GAN
genera 512 trayectorias del resto de la vela. P(Up) es la fracción que termina sobre el precio a superar.

**Kelly binario.** Comprar una acción a precio `a` con probabilidad `p`: `f* = (p − a) / (1 − a)`,
multiplicada por la fracción del perfil (10 % / 25 % / 50 %) y limitada por un tope del bankroll.

## Instalación (Apple Silicon, macOS 14+, Python 3.11+)

```bash
git clone https://github.com/rmrodriguezgit/laya-mlx      # opcional: solo para leer el código
git clone https://github.com/rmrodriguezgit/Quantlabs-LY-KY-Q.git
cd Quantlabs-LY-KY-Q
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt                              # laya-mlx se instala desde PyPI
```

## Ejecución

```bash
# 1) Backend (la primera vez entrena GAN + agente Q con 7 días de datos: unos minutos)
cd backend
../.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8001

# 2) Dashboard
cd frontend && npm install
VITE_LAYA_WS=ws://127.0.0.1:8001/ws VITE_LAYA_API=http://127.0.0.1:8001 npm run dev -- --host 127.0.0.1
```

Opciones útiles:

- `python laya_mlx_engine.py train` reentrena y guarda en `backend/models/`.
- `LAYA_SYNTHETIC=1 python server.py` usa datos simulados, sin red (para probar el dashboard).
- La compuerta Laya se activa automáticamente en cada reinicio (descarga `aac6fef/laya-mlx` la primera vez).
  Puede desactivarse temporalmente desde el panel; el siguiente arranque vuelve a activarla.
- `VITE_LAYA_WS` y `VITE_LAYA_API` cambian las direcciones del backend en el frontend.

## Lo que debes saber antes de confiar en una señal

1. **Evaluación simulada.** No hay histórico de libros de Polymarket, así que el agente se entrena y se
   evalúa contra un mercado simulado (probabilidad por distancia al strike + ruido). Cualquier ganancia
   en esa evaluación viene en parte del ruido inyectado: no es evidencia de ventaja real.
2. **Fuente de precio.** Polymarket resuelve con Chainlink; yfinance puede ir con retraso y no coincide
   exactamente. El strike se aproxima con la apertura de la barra de 1 min (el panel avisa cuando es aproximado).
3. **Lectura de Polymarket sin probar en vivo.** Gamma (`btc-updown-5m-<epoch>`) y CLOB `/book` están
   implementados de forma defensiva; si fallan, el panel marca las cuotas como simuladas.
4. **Comisiones.** El parámetro de comisión es manual (0 % por defecto). Revisa las comisiones vigentes del mercado.
5. **Laya no está entrenado para finanzas.** Su veto es una lectura zero-shot del estado; no es un predictor.
6. **Datos limitados.** Yahoo da ~7 días de barras de 1 min; la GAN con tan pocos datos es frágil.
   Compara siempre el Brier del modelo contra el del mercado antes de usarlo.

Los paper trades se guardan en `backend/trades.jsonl`.


## Versionado y actualizaciones

La versión se mantiene en `frontend/package.json` y aparece automáticamente en el encabezado. Cada actualización debe incrementar la versión según SemVer, sincronizar `frontend/package-lock.json`, actualizar este README y crear un commit. Publicar los commits en `origin/main` según la autorización del propietario.

## Historial de versiones

### v0.1.1 — 2026-10-17

- Compuerta Laya activada por defecto en cada arranque, sin depender de variables de entorno.
- El control del panel permite desactivarla durante la sesión actual.

### v0.1.0 — 2026-10-17

- Primera publicación de Quantlabs LY-KY-Q.
- Dashboard React con logo Quantlabs, favicon y versión visible.
- Motor MLX con GAN, agente Q y compuerta Laya opcional.
- Lectura del libro real de Polymarket y precio BTC desde yfinance.
- Paper trading con tamaño de posición Kelly y bitácora local.
- Compilación del frontend verificada con `npm run build`.

El arranque documentado utiliza el puerto 8001; `python server.py` conserva el puerto predeterminado 8000.
