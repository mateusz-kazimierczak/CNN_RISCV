import type { ReactNode } from "react";
import { Layers3 } from "lucide-react";

export function WorkspaceHeader({
  navigation,
  children,
}: {
  navigation?: ReactNode;
  children: ReactNode;
}) {
  return (
    <header className="topbar workspace-header">
      <div className="brand">
        <div className="brand-symbol">
          <Layers3 size={21} />
        </div>
        <div>
          <strong>
            Execution Atlas<span> /</span>
          </strong>
          <small>MODEL TO MACHINE</small>
        </div>
      </div>
      {navigation}
      {children}
    </header>
  );
}
