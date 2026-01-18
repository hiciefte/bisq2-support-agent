import { getApiBaseUrl } from './config';

/**
 * Public FAQ types - sanitized version of FAQs for public consumption
 */
export interface PublicFAQ {
  id: string;
  slug: string;
  question: string;
  answer: string;
  category: string;
  updated_at?: string;
}

export interface PublicFAQCategory {
  name: string;
  slug: string;
  count: number;
}

export interface Pagination {
  page: number;
  limit: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

export interface PublicFAQListResponse {
  data: PublicFAQ[];
  pagination: Pagination;
}

export interface PublicFAQCategoriesResponse {
  categories: PublicFAQCategory[];
}

/**
 * Fetch paginated list of public FAQs
 */
export async function fetchPublicFAQs(options?: {
  page?: number;
  limit?: number;
  search?: string;
  category?: string;
}): Promise<PublicFAQListResponse> {
  const params = new URLSearchParams();
  if (options?.page) params.set('page', String(options.page));
  if (options?.limit) params.set('limit', String(options.limit));
  if (options?.search) params.set('search', options.search);
  if (options?.category) params.set('category', options.category);

  const queryString = params.toString();
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/public/faqs${queryString ? `?${queryString}` : ''}`;

  const response = await fetch(url, {
    method: 'GET',
    headers: {
      'Accept': 'application/json',
    },
    // Allow caching for public FAQ data
    next: { revalidate: 900 }, // 15 minutes (matches backend Cache-Control)
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch FAQs: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Fetch a single FAQ by its slug
 */
export async function fetchPublicFAQBySlug(slug: string): Promise<PublicFAQ | null> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/public/faqs/${encodeURIComponent(slug)}`;

  const response = await fetch(url, {
    method: 'GET',
    headers: {
      'Accept': 'application/json',
    },
    next: { revalidate: 900 }, // 15 minutes
  });

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    throw new Error(`Failed to fetch FAQ: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Fetch all FAQ categories with counts
 */
export async function fetchPublicFAQCategories(): Promise<PublicFAQCategory[]> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/public/faqs/categories`;

  const response = await fetch(url, {
    method: 'GET',
    headers: {
      'Accept': 'application/json',
    },
    next: { revalidate: 1800 }, // 30 minutes (categories change less frequently)
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch categories: ${response.statusText}`);
  }

  const data: PublicFAQCategoriesResponse = await response.json();
  return data.categories;
}

/**
 * Fetch all FAQ slugs for static generation
 * Used by generateStaticParams in FAQ detail page
 * Paginates through all pages to collect all slugs
 */
export async function fetchAllFAQSlugs(): Promise<string[]> {
  const allSlugs: string[] = [];
  const limit = 50; // Fetch in smaller batches
  let page = 1;
  let hasMore = true;

  try {
    const baseUrl = getApiBaseUrl();

    while (hasMore) {
      const response = await fetch(
        `${baseUrl}/api/public/faqs?limit=${limit}&page=${page}`,
        {
          method: 'GET',
          headers: {
            Accept: 'application/json',
          },
          next: { revalidate: 3600 }, // Cache for 1 hour
        }
      );

      if (!response.ok) {
        console.error('Failed to fetch FAQ slugs:', response.status);
        break;
      }

      const data: PublicFAQListResponse = await response.json();
      const slugs = data.data?.map((faq: PublicFAQ) => faq.slug) || [];
      allSlugs.push(...slugs);

      hasMore = data.pagination.has_next;
      page++;
    }

    return allSlugs;
  } catch (error) {
    console.error('Error fetching FAQ slugs:', error);
    return allSlugs; // Return whatever we collected so far
  }
}
