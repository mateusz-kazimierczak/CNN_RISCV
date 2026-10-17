import {
  lazy,
  Suspense,
  useEffect,
  useLayoutEffect,
  useState,
  useRef,
  type KeyboardEvent,
} from "react";
import { Activity, Cpu, LoaderCircle } from "lucide-react";
import type { SimulationSession } from "./simulator/types";
import { WorkspaceHeader } from "./WorkspaceHeader";
import "./workbench.css";

const Explorer = lazy(() => import("./App").then((m) => ({ default: m.App })));
const Simulator = lazy(() =>
  import("./simulator/App").then((m) => ({ default: m.Simulator })),
);
type Workspace = "explorer" | "simulator";
function currentWorkspace(): Workspace {
  if (location.hash === "#explorer") return "explorer";
  return location.hash === "#simulator" ||
    location.pathname.endsWith("/simulator.html")
    ? "simulator"
    : "explorer";
}
export function Workbench() {
  const [workspace, setWorkspace] = useState(currentWorkspace);
  const pendingTabFocus = useRef(false);
  const [visited, setVisited] = useState(() => ({
    explorer: workspace === "explorer",
    simulator: workspace === "simulator",
  }));
  const [simulationStatus, setSimulationStatus] =
    useState<SimulationSession["status"]>("disconnected");
  useEffect(() => {
    const update = () => {
      const next = currentWorkspace();
      setWorkspace(next);
      setVisited((previous) => ({ ...previous, [next]: true }));
    };
    window.addEventListener("hashchange", update);
    window.addEventListener("popstate", update);
    return () => {
      window.removeEventListener("hashchange", update);
      window.removeEventListener("popstate", update);
    };
  }, []);
  useEffect(() => {
    document.title = `Execution Atlas · ${workspace === "explorer" ? "Explorer" : "Simulator"}`;
  }, [workspace]);
  useLayoutEffect(() => {
    // Each view keeps its own header; restore focus to the visible tab.
    if (
      pendingTabFocus.current ||
      document.activeElement?.closest(".workspace-view[hidden]")
    )
      document
        .getElementById(`tab-${workspace}`)
        ?.focus({ preventScroll: true });
    pendingTabFocus.current = false;
  }, [workspace]);
  function navigate(next: Workspace) {
    pendingTabFocus.current = next !== workspace;
    location.hash = next;
  }
  function tabKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? "explorer"
        : event.key === "End"
          ? "simulator"
          : workspace === "explorer"
            ? "simulator"
            : "explorer";
    event.currentTarget
      .closest('[role="tablist"]')
      ?.querySelector<HTMLButtonElement>(`[data-workspace="${next}"]`)
      ?.focus();
    navigate(next);
  }
  const navigation = (
    <div className="workspace-tabs" role="tablist" aria-label="Workspace">
      {(["explorer", "simulator"] as const).map((name) => (
        <button
          key={name}
          role="tab"
          id={`tab-${name}`}
          data-workspace={name}
          aria-label={
            name === "explorer"
              ? "Explorer"
              : `Simulator${
                  ["running", "paused"].includes(simulationStatus)
                    ? ` ${simulationStatus}`
                    : ""
                }`
          }
          aria-controls={`panel-${name}`}
          aria-selected={workspace === name}
          tabIndex={workspace === name ? 0 : -1}
          onClick={() => navigate(name)}
          onKeyDown={tabKey}
        >
          {name === "explorer" ? <Activity size={15} /> : <Cpu size={15} />}
          {name === "explorer" ? "Explorer" : "Simulator"}
          {name === "simulator" &&
            ["running", "paused"].includes(simulationStatus) && (
              <span className={`workspace-session ${simulationStatus}`}>
                {simulationStatus}
              </span>
            )}
        </button>
      ))}
    </div>
  );
  const loading = (name: Workspace) => (
    <>
      <WorkspaceHeader navigation={workspace === name ? navigation : undefined}>
        <span />
      </WorkspaceHeader>
      <div className="loading">
        <LoaderCircle size={16} className="spin" /> Opening workspace…
      </div>
    </>
  );
  return (
    <>
      <section
        id="panel-explorer"
        role="tabpanel"
        aria-labelledby="tab-explorer"
        className="workspace-view"
        hidden={workspace !== "explorer"}
      >
        {visited.explorer && (
          <Suspense fallback={loading("explorer")}>
            <Explorer
              active={workspace === "explorer"}
              navigation={workspace === "explorer" ? navigation : undefined}
            />
          </Suspense>
        )}
      </section>
      <section
        id="panel-simulator"
        role="tabpanel"
        aria-labelledby="tab-simulator"
        className="workspace-view"
        hidden={workspace !== "simulator"}
      >
        {visited.simulator && (
          <Suspense fallback={loading("simulator")}>
            <Simulator
              active={workspace === "simulator"}
              navigation={workspace === "simulator" ? navigation : undefined}
              onStatusChange={setSimulationStatus}
            />
          </Suspense>
        )}
      </section>
    </>
  );
}
