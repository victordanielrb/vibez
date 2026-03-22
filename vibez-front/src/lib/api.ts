const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:3001";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("vibez_token");
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<T>;
}

export async function apiPostFormData<T>(
  path: string,
  formData: FormData
): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: {
      // Do NOT set Content-Type — browser sets multipart boundary automatically
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: formData,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<T>;
}

export function saveToken(token: string): void {
  localStorage.setItem("vibez_token", token);
}

export function clearToken(): void {
  localStorage.removeItem("vibez_token");
}
