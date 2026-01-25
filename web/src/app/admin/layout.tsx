import { AdminSidebar } from "@/components/admin/sidebar";
import { SecureAuth } from "@/components/admin/SecureAuth";
// Toaster is provided by root layout - no duplicate needed here

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <SecureAuth>
      <div className="min-h-screen bg-background">
        <div className="flex">
          <AdminSidebar />
          <main className="flex-1">
            {children}
          </main>
        </div>
      </div>
    </SecureAuth>
  )
}
