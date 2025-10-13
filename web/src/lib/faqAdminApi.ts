import { API_BASE_URL } from './config';
import { makeAuthenticatedRequest } from './auth';

// Define types (can be shared or re-defined from the page component)
interface FAQItemData {
  question: string;
  answer: string;
  category?: string;
  source?: string;
}

interface FAQIdentifiedItem extends FAQItemData {
  id: string;
}

interface FAQListResponse {
  faqs: FAQIdentifiedItem[];
}

/**
 * Generic helper function to reduce code duplication across CRUD operations
 */
async function makeFaqRequest(
  endpoint: string,
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  apiKey: string,
  body?: FAQItemData
): Promise<FAQListResponse> {
  const response = await makeAuthenticatedRequest(`${API_BASE_URL}/api${endpoint}`, {
    method,
    headers: {
      'Authorization': `Bearer ${apiKey}`,
    },
    ...(body && { body: JSON.stringify(body) }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(`FAQ request failed: ${errorData.detail || response.statusText}`);
  }

  return response.json();
}

async function fetchFaqs(apiKey: string): Promise<FAQListResponse> {
  return makeFaqRequest('/admin/faqs', 'GET', apiKey);
}

async function addFaq(apiKey: string, faqData: FAQItemData): Promise<FAQListResponse> {
  return makeFaqRequest('/admin/faqs', 'POST', apiKey, faqData);
}

async function updateFaq(apiKey: string, faqId: string, faqData: FAQItemData): Promise<FAQListResponse> {
  return makeFaqRequest(`/admin/faqs/${faqId}`, 'PUT', apiKey, faqData);
}

async function deleteFaq(apiKey: string, faqId: string): Promise<FAQListResponse> {
  return makeFaqRequest(`/admin/faqs/${faqId}`, 'DELETE', apiKey);
}

export {
    fetchFaqs,
    addFaq,
    updateFaq,
    deleteFaq
};

export type { FAQItemData, FAQIdentifiedItem, FAQListResponse };
