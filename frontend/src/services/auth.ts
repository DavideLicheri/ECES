/**
 * Authentication service for ECES Frontend
 */

export interface User {
  id: string;
  username: string;
  email: string;
  full_name: string;
  role: 'super_admin' | 'rings_admin' | 'user' | 'viewer';
  department?: string;
  is_active: boolean;
  created_at: string;
  last_login?: string;
  consents_to_aggregate_analysis?: boolean;
  // Campi per rings_admin (14/08/2026, piramide ruoli/livelli). Assegnati
  // dal super_admin via PUT /api/auth/users/rings-admin-assignment
  // (02/09/2026). Irrilevanti/assenti per gli altri ruoli.
  ringing_scheme?: string;
  territory_place_codes?: string[];
  // Promozione automatica viewer->user (punto aperto 2 del documento di
  // design, deciso con Davide 08/09/2026): avviso una tantum, presente SOLO
  // nella risposta di /login o /me immediatamente successiva alla
  // promozione lato server (che lo consuma subito dopo averlo esposto qui).
  // Non usare direttamente questo campo per mostrare il banner -- vedi
  // AuthService.consumePendingPromotionNotice(), che lo rende persistente
  // anche attraverso la seconda chiamata /me ridondante che segue il login.
  pending_promotion_notice?: boolean;
}

export interface RingsAdminAssignmentUpdate {
  username: string;
  ringing_scheme?: string | null;
  territory_place_code?: string | null;
}

export interface ConsentUpdateRequest {
  consents: boolean;
}

export interface ConsentUpdateResponse {
  success: boolean;
  consents_to_aggregate_analysis: boolean;
  message?: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface UserPermissions {
  user: string;
  role: string;
  permissions: {
    can_view: boolean;
    can_use_recognition: boolean;
    can_use_conversion: boolean;
    can_view_matrix: boolean;
    can_edit_matrix: boolean;
    can_manage_users: boolean;
    can_access_admin: boolean;
  };
}

export interface PasswordChangeRequest {
  current_password: string;
  new_password: string;
}

export interface PasswordChangeResponse {
  success: boolean;
  message: string;
}

class AuthService {
  private baseURL = `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/api/auth`;
  private tokenKey = 'eces_token';
  private userKey = 'eces_user';
  // Flag "sticky", separato da eces_user (promozione automatica viewer->user,
  // 08/09/2026): sia login() sia getCurrentUser() possono osservare
  // pending_promotion_notice=true nella LORO singola risposta -- ma App.tsx
  // chiama getCurrentUser() una seconda volta subito dopo un login riuscito
  // (handleLoginSuccess), e quella seconda chiamata /me arriva quando il
  // flag e' gia' stato consumato lato server, quindi risponde gia' false e
  // sovrascriverebbe eces_user perdendo il segnale. Questa chiave separata
  // non viene mai sovrascritta a false, solo scritta a true e poi rimossa
  // esplicitamente da consumePendingPromotionNotice() quando la UI la mostra.
  private pendingPromotionKey = 'eces_pending_promotion_notice';

  // Get stored token
  getToken(): string | null {
    return localStorage.getItem(this.tokenKey);
  }

  // Get stored user
  getUser(): User | null {
    const userStr = localStorage.getItem(this.userKey);
    return userStr ? JSON.parse(userStr) : null;
  }

  // Check if user is authenticated
  isAuthenticated(): boolean {
    const token = this.getToken();
    const user = this.getUser();
    return !!(token && user);
  }

  // Check if user is Super Admin
  isSuperAdmin(): boolean {
    const user = this.getUser();
    return user?.role === 'super_admin';
  }

  // Login
  async login(credentials: LoginRequest): Promise<LoginResponse> {
    const response = await fetch(`${this.baseURL}/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(credentials),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Login failed');
    }

    const data: LoginResponse = await response.json();

    // Store token and user
    localStorage.setItem(this.tokenKey, data.access_token);
    localStorage.setItem(this.userKey, JSON.stringify(data.user));
    if (data.user.pending_promotion_notice) {
      localStorage.setItem(this.pendingPromotionKey, '1');
    }

    return data;
  }

  // Logout
  async logout(): Promise<void> {
    const token = this.getToken();
    
    if (token) {
      try {
        await fetch(`${this.baseURL}/logout`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });
      } catch (error) {
        console.warn('Logout request failed:', error);
      }
    }
    
    // Clear local storage
    localStorage.removeItem(this.tokenKey);
    localStorage.removeItem(this.userKey);
    localStorage.removeItem(this.pendingPromotionKey);
  }

  // Get current user info from server
  async getCurrentUser(): Promise<User> {
    const token = this.getToken();
    
    if (!token) {
      throw new Error('No authentication token');
    }

    const response = await fetch(`${this.baseURL}/me`, {
      headers: {
        'Authorization': `Bearer ${token}`,
      },
    });

    if (!response.ok) {
      if (response.status === 401) {
        this.logout(); // Clear invalid token
      }
      throw new Error('Failed to get user info');
    }

    const user: User = await response.json();
    localStorage.setItem(this.userKey, JSON.stringify(user));
    if (user.pending_promotion_notice) {
      localStorage.setItem(this.pendingPromotionKey, '1');
    }
    return user;
  }

  // Legge e CANCELLA il flag "promozione in sospeso" (promozione automatica
  // viewer->user, 08/09/2026): va mostrato una volta sola all'utente, poi
  // non deve ripresentarsi ad ogni refresh/render successivo. Vedi il
  // commento su pendingPromotionKey sopra per il perche' di questa chiave
  // separata da eces_user.
  consumePendingPromotionNotice(): boolean {
    const wasPending = localStorage.getItem(this.pendingPromotionKey) === '1';
    if (wasPending) {
      localStorage.removeItem(this.pendingPromotionKey);
    }
    return wasPending;
  }

  // Get user permissions
  async getUserPermissions(): Promise<UserPermissions> {
    const token = this.getToken();
    
    if (!token) {
      throw new Error('No authentication token');
    }

    const response = await fetch(`${this.baseURL}/permissions`, {
      headers: {
        'Authorization': `Bearer ${token}`,
      },
    });

    if (!response.ok) {
      throw new Error('Failed to get permissions');
    }

    return response.json();
  }

  // Get authorization header
  getAuthHeader(): Record<string, string> {
    const token = this.getToken();
    return token ? { 'Authorization': `Bearer ${token}` } : {};
  }

  // Check if token is expired (basic check)
  isTokenExpired(): boolean {
    const user = this.getUser();
    if (!user) return true;

    // Simple check - in production you might want to decode JWT
    const now = Date.now();
    const loginTime = new Date(user.last_login || user.created_at).getTime();
    const eightHours = 8 * 60 * 60 * 1000; // 8 hours in milliseconds
    
    return (now - loginTime) > eightHours;
  }

  // Change password
  async changePassword(passwordData: PasswordChangeRequest): Promise<PasswordChangeResponse> {
    const token = this.getToken();
    
    if (!token) {
      throw new Error('No authentication token');
    }

    const response = await fetch(`${this.baseURL}/change-password`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify(passwordData),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Password change failed');
    }

    return response.json();
  }

  // Aggiorna il consenso all'analisi aggregata anonima (Lizzy)
  async updateConsent(consents: boolean): Promise<ConsentUpdateResponse> {
    const token = this.getToken();

    if (!token) {
      throw new Error('No authentication token');
    }

    const response = await fetch(`${this.baseURL}/consent`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ consents_to_aggregate_analysis: consents }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Aggiornamento consenso fallito');
    }

    const result: ConsentUpdateResponse = await response.json();

    // Aggiorna anche la copia locale dell'utente cosi' la UI resta coerente
    const user = this.getUser();
    if (user) {
      user.consents_to_aggregate_analysis = result.consents_to_aggregate_analysis;
      localStorage.setItem(this.userKey, JSON.stringify(user));
    }

    return result;
  }
}

export const authService = new AuthService();