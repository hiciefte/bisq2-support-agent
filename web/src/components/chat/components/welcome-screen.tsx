/**
 * Welcome screen component shown when chat is empty
 */

import Image from "next/image"
import { MessageSquare, Plus } from "lucide-react"

interface WelcomeScreenProps {
    formattedAvgTime: string
}

export const WelcomeScreen = ({ formattedAvgTime }: WelcomeScreenProps) => {
    return (
        <div className="flex h-[calc(100vh-280px)] flex-col items-center justify-center">
            <div className="flex items-center justify-center space-x-3 mb-4">
                <Image
                    src="/bisq-fav.png"
                    alt="Bisq AI"
                    width={40}
                    height={40}
                    className="rounded"
                />
                <Plus className="h-5 w-5 text-muted-foreground" />
                <MessageSquare className="h-8 w-8 text-muted-foreground" />
            </div>
            <p className="text-lg font-medium mb-2">Welcome to Bisq Support AI</p>
            <p className="text-sm text-muted-foreground text-center max-w-sm mb-8">
                Meet your digital dumpster fire of wisdom! Our CPU-powered chaos takes
                about {formattedAvgTime} to answer, but the wait&#39;s worth it. Picture a
                caffeinated gremlin strapped to spare toaster parts, here to solve your Bisq 2
                questions!
            </p>
        </div>
    )
}
