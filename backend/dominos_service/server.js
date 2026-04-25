import express from 'express';
import { NearbyStores, Customer, Item, Order, Payment } from 'dominos';

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 3001;

// Default item codes by size/type
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
// Body: { address: string }
app.post('/nearby-stores', async (req, res) => {
  try {
    const { address } = req.body;
    if (!address) return res.status(400).json({ error: 'address required' });
    const result = await findNearestDeliveryStore(address);
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// POST /order
// Body: {
//   address, firstName, lastName, phone, email,
//   items: [{ code?, size?, quantity?, options? }],   — defaults to 14" hand tossed
//   payment?: { number, expiration, securityCode, postalCode, tipAmount }
// }
app.post('/order', async (req, res) => {
  try {
    const {
      address, firstName = 'Customer', lastName = '', phone = '555-555-5555', email = '',
      items = [{ code: ITEM_CODES.default }],
      payment,
    } = req.body;

    if (!address) return res.status(400).json({ error: 'address required' });

    const customer = new Customer({ address, firstName, lastName, phone, email });
    const { storeID, distance } = await findNearestDeliveryStore(address);

    const order = new Order(customer);
    order.storeID = storeID;

    for (const item of items) {
      const code = resolveItemCode(item);
      const domItem = new Item({ code, ...(item.options ? { options: item.options } : {}) });
      order.addItem(domItem);
    }

    await order.validate();
    await order.price();

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
      await order.place();
      result.placed = true;
      result.orderID = order.orderID ?? null;
    }

    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, () => console.log(`Dominos service on :${PORT}`));
