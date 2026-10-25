import { httpApi } from './http';
import { mockApi } from './mock';

const baseUrl = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();

export const usingMock = !baseUrl;
export const api = baseUrl ? httpApi(baseUrl) : mockApi;

export * from './types';
