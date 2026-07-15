import { ChatInterface } from "@/components/chat/chat-interface"
import { getPrivacyRetentionDays } from "@/lib/privacy-retention"

export const dynamic = "force-dynamic"

export default function Home() {
  const retentionDays = getPrivacyRetentionDays()

  return (
    <main className="h-screen">
      <ChatInterface retentionDays={retentionDays} />
    </main>
  )
}
