"use client";

export function PageHeading({
  title,
  children,
  actions,
}: {
  title: string;
  children?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[26px] font-semibold tracking-display text-white">
          {title}
        </h1>
        {children && (
          <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-dim">
            {children}
          </p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
