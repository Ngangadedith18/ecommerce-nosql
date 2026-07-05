import axios from 'axios';

const API = axios.create({ baseURL: 'http://localhost:8000' });

export const getTopProducts    = (n = 10) => API.get(`/products/top?n=${n}`);
export const getRevenueByCategory = ()   => API.get('/analytics/revenue-by-category');
export const getRevenueLast30Days = ()   => API.get('/analytics/revenue-last-30-days');
export const searchCatalogue   = (q, category, prix_min, prix_max) => {
  const params = new URLSearchParams({ q });
  if (category) params.append('category', category);
  if (prix_min) params.append('prix_min', prix_min);
  if (prix_max) params.append('prix_max', prix_max);
  return API.get(`/catalogue/search?${params}`);
};
export const getRecommendations = (customerId, depth = 3) =>
  API.get(`/recommendations/${customerId}?depth=${depth}`);
export const getRealtimeTop    = (n = 10) => API.get(`/sales/realtime-top?n=${n}`);
export const getHealth         = ()       => API.get('/health');
export const getCustomerOrders = (id)     => API.get(`/customers/${id}/orders`);