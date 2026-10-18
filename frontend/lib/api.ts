import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const baseURL = (API_BASE_URL === '/api' || API_BASE_URL === '') ? '' : API_BASE_URL;

const api = axios.create({
  baseURL: baseURL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use(
  (config) => {
    return config;
  },
  (error) => {
    console.error('❌ API Request Error:', error);
    return Promise.reject(error);
  }
);

api.interceptors.response.use(
  (response) => {
    return response;
  },
  (error) => {
    console.error('❌ API Response Error:');
    console.error('  Status:', error.response?.status);
    console.error('  URL:', error.config?.url);
    console.error('  Message:', error.message);
    return Promise.reject(error);
  }
);

export interface NewsArticle {
  id: number;
  title: string;
  summary?: string;
  content?: string;
  link: string;
  author?: string;
  published_date?: string;
  category: string;
  feed_id?: number;
  image_url?: string;
  slug?: string;
  created_at: string;
  updated_at?: string;
  feed_name?: string;
}

export interface NewsArticleList {
  articles: NewsArticle[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

export interface RSSFeed {
  id: number;
  name: string;
  url: string[];
  category: string;
  description?: string;
  is_active: boolean;
  created_at: string;
  updated_at?: string;
}


// API functions
export const newsApi = {
  // Get articles
  getArticles: async (params?: {
    source?: string;
    feeds?: string[];
    page?: number;
    per_page?: number;
    article_id?: number;
  }): Promise<NewsArticleList> => {
    const apiParams: any = { ...params };
    if (params?.feeds && params.feeds.length > 0) {
      apiParams.feeds = params.feeds.join(',');
    }
    const response = await api.get('/api/news/articles', { params: apiParams });
    console.log('✅ Fetched articles:', response.data);
    return response.data;
  },

  // Get feeds
  getFeeds: async (): Promise<RSSFeed[]> => {
    const response = await api.get('/api/news/feeds');
    return response.data;
  },

  // Add feed
  addFeed: async (feed: {
    name: string;
    url: string[];
    category: string;
  }): Promise<any> => {
    const response = await api.post('/api/news/feeds/add', feed);
    return response.data;
  },

  // Extract article content
  extractArticleContent: async (articleId: number): Promise<any> => {
    const response = await api.get(`/api/news/articles/${articleId}`);
    return response.data;
  },

  searchArticles: async (params: {
    query: string;
    time_filter?: string;
    page?: number;
    per_page?: number;
  }): Promise<NewsArticleList> => {
    const response = await api.get('/api/news/search', { params });
    return response.data;
  },
};
