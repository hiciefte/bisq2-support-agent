"use client"

import { useState, useEffect } from 'react'
import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { BarChart3, MessageSquare, HelpCircle, Menu, X, LogOut } from "lucide-react"

const navigation = [
  {
    name: "Overview",
    href: "/admin/overview",
    icon: BarChart3,
    description: "Dashboard and analytics"
  },
  {
    name: "Feedback",
    href: "/admin/manage-feedback",
    icon: MessageSquare,
    description: "Manage user feedback"
  },
  {
    name: "FAQs",
    href: "/admin/manage-faqs",
    icon: HelpCircle,
    description: "Manage FAQ content"
  }
]

export function AdminSidebar() {
  const [isMobileOpen, setIsMobileOpen] = useState(false)
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false)
  const pathname = usePathname()

  useEffect(() => {
    // Since we now use SecureAuth wrapper, we're only rendered when authenticated
    setIsAuthenticated(true);

    const handleAuthChange = () => {
      // This will be called when authentication status changes
      setIsAuthenticated(true);
    };

    const handleEscapeKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isMobileOpen) {
        setIsMobileOpen(false);
      }
    };

    window.addEventListener('admin-auth-changed', handleAuthChange);
    document.addEventListener('keydown', handleEscapeKey);

    return () => {
      window.removeEventListener('admin-auth-changed', handleAuthChange);
      document.removeEventListener('keydown', handleEscapeKey);
    };
  }, [isMobileOpen]);

  const handleLogout = async () => {
    try {
      // Import logout function dynamically to avoid import issues
      const { logout } = await import('@/lib/auth');
      await logout();
      // Notify SecureAuth to re-check authentication (will show login form)
      window.dispatchEvent(new CustomEvent('admin-auth-changed'));
    } catch (error) {
      console.error('Logout error:', error);
      // Even on error, trigger auth recheck to show login form
      window.dispatchEvent(new CustomEvent('admin-auth-changed'));
    }
  }

  const SidebarContent = () => (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-6 border-b border-border">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center">
            <img
              src="/bisq-fav.png"
              alt="Bisq Logo"
              className="h-8 w-8"
            />
          </div>
          <div className="flex flex-col">
            <h2 className="text-lg font-semibold">Bisq Support</h2>
            <p className="text-sm text-muted-foreground">Admin Dashboard</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-2">
        {navigation.map((item) => {
          const isActive = pathname.startsWith(item.href)
          return (
            <Link
              key={item.name}
              href={item.href}
              onClick={() => setIsMobileOpen(false)}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              )}
            >
              <item.icon className="h-4 w-4" />
              <div className="flex flex-col">
                <span>{item.name}</span>
                <span className="text-xs opacity-80">{item.description}</span>
              </div>
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-border">
        <Button
          variant="ghost"
          onClick={handleLogout}
          className="w-full justify-start gap-2 text-muted-foreground hover:text-foreground"
        >
          <LogOut className="h-4 w-4" />
          Logout
        </Button>
      </div>
    </div>
  )

  // Don't render anything if not authenticated
  if (!isAuthenticated) {
    return null;
  }

  return (
    <>
      {/* Mobile menu button */}
      <div className="lg:hidden fixed top-4 left-4 z-50">
        <Button
          variant="outline"
          size="icon"
          onClick={() => setIsMobileOpen(!isMobileOpen)}
          className="bg-background"
          aria-expanded={isMobileOpen}
          aria-label={isMobileOpen ? "Close navigation menu" : "Open navigation menu"}
          aria-controls="mobile-sidebar"
        >
          {isMobileOpen ? (
            <X className="h-4 w-4" />
          ) : (
            <Menu className="h-4 w-4" />
          )}
        </Button>
      </div>

      {/* Mobile overlay */}
      {isMobileOpen && (
        <div
          className="lg:hidden fixed inset-0 bg-black/50 z-40"
          onClick={() => setIsMobileOpen(false)}
        />
      )}

      {/* Desktop sidebar */}
      <div className="hidden lg:flex lg:w-64 lg:flex-col lg:fixed lg:inset-y-0 bg-card border-r border-border">
        <SidebarContent />
      </div>

      {/* Mobile sidebar */}
      <div
        id="mobile-sidebar"
        className={cn(
          "lg:hidden fixed inset-y-0 left-0 z-50 w-64 bg-card border-r border-border transform transition-transform duration-200 ease-in-out",
          isMobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <SidebarContent />
      </div>

      {/* Spacer for desktop layout - only when authenticated */}
      <div className="hidden lg:block lg:w-64 lg:flex-shrink-0" aria-hidden="true" />
    </>
  )
}
