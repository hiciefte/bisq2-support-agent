"use client"

import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2 } from "lucide-react";
import { loginWithApiKey, logout, makeAuthenticatedRequest, registerSessionTimeoutCallback } from '@/lib/auth';

interface SecureAuthProps {
  children: React.ReactNode;
  onAuthChange?: (authenticated: boolean) => void;
}

export function SecureAuth({ children, onAuthChange }: SecureAuthProps) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [isCheckingAuth, setIsCheckingAuth] = useState<boolean>(true);
  const [loginError, setLoginError] = useState<string>('');
  const [isLoggingIn, setIsLoggingIn] = useState<boolean>(false);

  useEffect(() => {
    // Register session timeout callback
    registerSessionTimeoutCallback(() => {
      console.log('Session timeout detected, redirecting to login');
      setIsAuthenticated(false);
      onAuthChange?.(false);
      setLoginError('Your session has expired. Please log in again.');
    });

    checkAuthentication();
  }, [onAuthChange]);

  const checkAuthentication = async () => {
    try {
      // Try to make an authenticated request to check if we're logged in
      const response = await makeAuthenticatedRequest('/admin/dashboard/overview');
      const authenticated = response.ok;
      setIsAuthenticated(authenticated);
      onAuthChange?.(authenticated);
    } catch (error) {
      console.error('Auth check failed:', error);
      setIsAuthenticated(false);
      onAuthChange?.(false);
    } finally {
      setIsCheckingAuth(false);
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    const formData = new FormData(e.target as HTMLFormElement);
    const apiKey = formData.get('apiKey') as string;

    if (!apiKey) return;

    setIsLoggingIn(true);
    setLoginError('');

    try {
      await loginWithApiKey(apiKey);
      setIsAuthenticated(true);
      onAuthChange?.(true);
      // Clear the form
      (e.target as HTMLFormElement).reset();
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : 'Login failed');
    } finally {
      setIsLoggingIn(false);
    }
  };

  const handleLogout = async () => {
    try {
      await logout();
    } catch (error) {
      console.error('Logout error:', error);
    }
    setIsAuthenticated(false);
    onAuthChange?.(false);
  };

  if (isCheckingAuth) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle className="text-2xl font-bold text-center">Admin Login</CardTitle>
            <CardDescription>Enter your API key to access the admin dashboard.</CardDescription>
          </CardHeader>
          <form onSubmit={handleLogin}>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="apiKey">API Key</Label>
                <Input
                  id="apiKey"
                  name="apiKey"
                  type="password"
                  required
                  autoComplete="current-password"
                  disabled={isLoggingIn}
                />
              </div>
              {loginError && (
                <p className="text-sm text-red-500">{loginError}</p>
              )}
              <Button type="submit" className="w-full" disabled={isLoggingIn}>
                {isLoggingIn ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Logging in...
                  </>
                ) : (
                  'Login'
                )}
              </Button>
            </CardContent>
          </form>
        </Card>
      </div>
    );
  }

  return (
    <div>
      {/* Add a logout button that can be accessed from authenticated content */}
      <div className="hidden">
        <Button onClick={handleLogout} variant="ghost">
          Logout
        </Button>
      </div>
      {children}
    </div>
  );
}
