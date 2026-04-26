import express from 'express';
import { NearbyStores, Customer, Item, Order, Payment, Address } from 'dominos';

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 3001;

const ITEM_CODES = {
  'small':   '10SCREEN',
  'medium':  '12SCREEN',
  'large':   '14SCREEN',
  'xlarge':  '16SCREEN',
  'default': '14SCREEN',
};

function resolveItemCode(item) {
  if (item.code) return item.code;
  const size = (item.size || 'default').toLowerCase();
  return ITEM_CODES[size] || ITEM_CODES.default;
}

async function findNearestDeliveryStore(address) {
  const nearby = await new NearbyStores(address);
  let storeID = 0, distance = 100;
  for (const store of nearby.stores) {
    if (
      store.IsOnlineCapable &&
      store.IsDeliveryStore &&
      store.IsOpen &&
      store.ServiceIsOpen?.Delivery &&
      store.MinDistance < distance
    ) {
      distance = store.MinDistance;
      storeID = store.StoreID;
    }
  }
  if (storeID === 0) throw new Error('No open delivery stores found nearby');
  return { storeID, distance };
}

// GET /health
app.get('/health', (_req, res) => res.json({ status: 'ok' }));

// POST /nearby-stores
app.post('/nearby-stores', async (req, res) => {
  try {
    const { address } = req.body;
    if (!address) return res.status(400).json({ error: 'address required' });
    const result = await findNearestDeliveryStore(address);
    res.json(result);
  } catch (err) {
    console.error('[nearby-stores] error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// POST /order
app.post('/order', async (req, res) => {
  console.log('[order] request:', JSON.stringify(req.body, null, 2));
  try {
    const {
      address: rawAddress,
      firstName = 'Customer', lastName = '', phone = '5555555555', email = '',
      items = [{ code: ITEM_CODES.default }],
      payment,
    } = req.body;

    if (!rawAddress) return res.status(400).json({ error: 'address required' });

    // Use Address object for reliable parsing
    const address = new Address(rawAddress);
    console.log('[order] parsed address:', address);

    const customer = new Customer({ address, firstName, lastName, phone, email });
    const { storeID, distance } = await findNearestDeliveryStore(address);
    console.log('[order] storeID:', storeID, 'distance:', distance);

    const order = new Order(customer);
    order.storeID = storeID;

    for (const item of items) {
      const code = resolveItemCode(item);
      console.log('[order] adding item code:', code, 'options:', item.options);
      const domItem = new Item({ code, ...(item.options ? { options: item.options } : {}) });
      order.addItem(domItem);
    }

    console.log('[order] validating...');
    await order.validate();
    console.log('[order] pricing...');
    await order.price();
    console.log('[order] price:', order.amountsBreakdown?.customer);

    const result = {
      storeID,
      distance,
      price: order.amountsBreakdown?.customer,
      placed: false,
    };

    if (payment) {
      const card = new Payment({
        amount:       order.amountsBreakdown.customer,
        number:       payment.number,
        expiration:   payment.expiration,
        securityCode: payment.securityCode,
        postalCode:   payment.postalCode,
        tipAmount:    payment.tipAmount ?? 3,
      });
      order.payments.push(card);
      console.log('[order] placing order...');
      await order.place();
      result.placed = true;
      result.orderID = order.orderID ?? null;
      console.log('[order] placed! orderID:', result.orderID);
    }

    res.json(result);
  } catch (err) {
    console.error('[order] error:', err.message);
    console.error('[order] stack:', err.stack);
    res.status(500).json({ error: err.message, stack: err.stack });
  }
});

app.listen(PORT, () => console.log(`Dominos service on :${PORT}`));
