import ReactMarkdown from "react-markdown";

export interface SupportGuideProjection {
  page_id: string;
  title: string;
  protocol: string;
  revision: string;
  url: string;
  sections: { id: string; title: string; content: string; url: string }[];
}

export function GuideMarkdown({ children }: { children: string }) {
  return (
    <div className="prose prose-sm max-w-none dark:prose-invert">
      <ReactMarkdown skipHtml components={{ img: () => null }}>{children}</ReactMarkdown>
    </div>
  );
}

export function SupportGuideContent({ guide, preview = false }: { guide: SupportGuideProjection; preview?: boolean }) {
  const Title = preview ? "h3" : "h1";
  const SectionTitle = preview ? "h4" : "h2";
  const scope = ({ bisq_easy: "Bisq Easy (Bisq 2)", multisig_v1: "Bisq 1", all: "General Bisq guidance" } as Record<string, string>)[guide.protocol] || guide.protocol;
  return (
    <article className="space-y-6">
      <header className="space-y-2">
        <Title className="text-2xl font-semibold tracking-tight">{guide.title}</Title>
        <p className="text-sm text-muted-foreground">Product scope: {scope}</p>
      </header>
      {guide.sections.map((section) => (
        <section key={section.id} id={section.id} className="scroll-mt-6 space-y-3">
          <SectionTitle className="text-lg font-semibold">
            <a href={`#${section.id}`}>{section.id === "canonical-support-answer" ? "Guidance" : section.id === "applies-when" ? "When this applies" : section.title}</a>
          </SectionTitle>
          <GuideMarkdown>{section.content}</GuideMarkdown>
        </section>
      ))}
    </article>
  );
}
