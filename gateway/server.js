require('./tracing');

const express = require('express');

const app = express();
const port = Number(process.env.PORT || 3000);
const orderServiceUrl = process.env.ORDER_SERVICE_URL || 'http://order-service:8000';

app.use(express.json());

app.get('/', (_req, res) => {
  res.json({ service: 'gateway', status: 'ok', health: '/health', orders: '/api/orders' });
});

async function proxyToOrderService(req, res, next) {
  try {
    const response = await fetch(`${orderServiceUrl}/orders`, {
      method: req.method,
      headers: {
        'content-type': 'application/json',
      },
      body: req.method === 'POST' ? JSON.stringify(req.body) : undefined,
    });

    const contentType = response.headers.get('content-type');
    if (contentType) {
      res.set('content-type', contentType);
    }

    const responseBody = await response.text();
    res.status(response.status).send(responseBody);
  } catch (error) {
    next(error);
  }
}

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', service: 'gateway' });
});

app.get('/api/orders', proxyToOrderService);
app.post('/api/orders', proxyToOrderService);

app.use((_req, res) => {
  res.status(404).json({ detail: 'Route not found' });
});

app.use((error, _req, res, _next) => {
  console.error(error);
  res.status(502).json({ detail: 'Order Service is unavailable' });
});

app.listen(port, () => {
  console.log(`Gateway listening on port ${port}`);
});
