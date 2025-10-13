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

const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || `http://${hostname}:8000/api`;

async function fetchFaqs(apiKey: string): Promise<FAQListResponse> {
  const response = await makeAuthenticatedRequest(`${API_BASE_URL}/admin/faqs`, {
    method: 'GET',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
    },
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(`Failed to fetch FAQs: ${errorData.detail || response.statusText}`);
  }
  return response.json();
}

async function addFaq(apiKey: string, faqData: FAQItemData): Promise<FAQListResponse> {
  const response = await makeAuthenticatedRequest(`${API_BASE_URL}/admin/faqs`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
    },
    body: JSON.stringify(faqData),
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(`Failed to add FAQ: ${errorData.detail || response.statusText}`);
  }
  return response.json();
}

async function updateFaq(apiKey: string, faqId: string, faqData: FAQItemData): Promise<FAQListResponse> {
  const response = await makeAuthenticatedRequest(`${API_BASE_URL}/admin/faqs/${faqId}`, {
    method: 'PUT',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
    },
    body: JSON.stringify(faqData),
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(`Failed to update FAQ ${faqId}: ${errorData.detail || response.statusText}`);
  }
  return response.json();
}

async function deleteFaq(apiKey: string, faqId: string): Promise<FAQListResponse> {
  const response = await makeAuthenticatedRequest(`${API_BASE_URL}/admin/faqs/${faqId}`, {
    method: 'DELETE',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
    },
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(`Failed to delete FAQ ${faqId}: ${errorData.detail || response.statusText}`);
  }
  return response.json();
}

export {
    fetchFaqs,
    addFaq,
    updateFaq,
    deleteFaq
};

export type { FAQItemData, FAQIdentifiedItem, FAQListResponse };
