import React from "react";
import { createRoot } from "react-dom/client";
import { Simulator } from "./App";
import "../style.css";
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Simulator />
  </React.StrictMode>,
);
