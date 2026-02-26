import NextTopLoader from 'nextjs-toploader';
import { AdminSidebar } from "@/components/admin/sidebar";
import { SecureAuth } from "@/components/admin/SecureAuth";
import { AdminQueryClientProvider } from "@/components/providers/query-client-provider";
// Toaster is provided by root layout - no duplicate needed here

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <SecureAuth>
      <AdminQueryClientProvider>
        <NextTopLoader color="#f7931a" showSpinner={false} />
        <div className="min-h-screen bg-background">
          <div className="flex">
            <AdminSidebar />
            <main className="flex-1">
              {children}
            </main>
          </div>
        </div>
      </AdminQueryClientProvider>
    </SecureAuth>
  )
}
