// Appended to the ordinary full-inference monitor only for custom checkpoints.
// Keep a separate state machine so simultaneous monitor blocks cannot race on
// project_active. Count committed instruction encodings, never Decode activity.
longint unsigned project_qmac = 0, project_requant = 0;
longint unsigned project_expected_qmac = 0, project_expected_requant = 0;
longint unsigned project_postload = 0, project_poststore = 0;
longint unsigned project_expected_postload = 0, project_expected_poststore = 0;
logic project_postinc_enabled = 0;
logic project_bank_enabled = 0;
// Exact reserved-field checks for the nine bank forms. The X4-only monitor
// maintains their counters separately from the arithmetic/postincrement file.
function automatic integer project_bank_index(input logic [31:0] bits);
  project_bank_index = -1;
  if ((bits & 32'hfe007fff) == 32'h0000200b) project_bank_index = 0;
  for (int pair_index = 0; pair_index < 4; pair_index++) begin
    if ((bits & 32'hfff07fff) == (32'h0000300b | (32'(pair_index) << 25)))
      project_bank_index = pair_index + 1;
    if ((bits & 32'hfffff07f) == (32'h0000400b | (32'(pair_index) << 25)))
      project_bank_index = pair_index + 5;
  end
endfunction
logic project_custom_active = 0;
integer project_custom_file = 0;
string project_custom_path;
initial begin
  project_bank_enabled = $test$plusargs("PROJECT_BANK");
  if (!$value$plusargs("PROJECT_EXPECTED_QMAC=%d", project_expected_qmac)) project_expected_qmac = 0;
  if (!$value$plusargs("PROJECT_EXPECTED_REQUANT=%d", project_expected_requant)) project_expected_requant = 0;
  project_postinc_enabled = $value$plusargs("PROJECT_EXPECTED_POSTLOAD=%d", project_expected_postload);
  if (project_postinc_enabled && !$value$plusargs("PROJECT_EXPECTED_POSTSTORE=%d", project_expected_poststore))
    $fatal(1, "Missing expected post-increment store count");
  if (!$value$plusargs("PROJECT_CUSTOM_METRICS=%s", project_custom_path))
    $fatal(1, "Missing custom retirement output path");
  project_custom_file = $fopen(project_custom_path, "w");
  if (project_custom_file == 0) $fatal(1, "Cannot open custom retirement output");
end
always @(posedge clk) begin
  if (reset) begin
    project_custom_active = 0;
    project_qmac = 0;
    project_requant = 0;
    project_postload = 0;
    project_poststore = 0;
  end else if (project_commit) begin
    if (PCM == project_entry) project_custom_active = 1;
    if (project_custom_active && PCM == project_return) begin
      project_custom_active = 0;
      if (project_qmac != project_expected_qmac || project_requant != project_expected_requant ||
          project_postload != project_expected_postload || project_poststore != project_expected_poststore)
        $fatal(1, "Custom retirements disagree: qmac=%0d/%0d requant=%0d/%0d postload=%0d/%0d poststore=%0d/%0d",
          project_qmac, project_expected_qmac, project_requant, project_expected_requant,
          project_postload, project_expected_postload, project_poststore, project_expected_poststore);
      if (project_postinc_enabled)
        $fdisplay(project_custom_file, "{\"xqmac8\":\"%0d\",\"xrequant\":\"%0d\",\"xpostinc_load\":\"%0d\",\"xpostinc_store\":\"%0d\"}", project_qmac, project_requant, project_postload, project_poststore);
      else
        $fdisplay(project_custom_file, "{\"xqmac8\":\"%0d\",\"xrequant\":\"%0d\"}", project_qmac, project_requant);
      $fclose(project_custom_file);
      $display("PROJECT custom complete xqmac8=%0d xrequant=%0d postload=%0d poststore=%0d", project_qmac, project_requant, project_postload, project_poststore);
    end else if (project_custom_active && InstrM[6:0] == 7'h0b) begin
      case (InstrM & 32'hfe00707f)
        32'h0000000b: project_qmac = project_qmac + 1;
        32'h0000100b: project_requant = project_requant + 1;
        default: if (!project_bank_enabled || project_bank_index(InstrM) < 0)
          $fatal(1, "Unknown committed custom encoding: %h", InstrM);
      endcase
    end else if (project_custom_active && InstrM[6:0] == 7'h2b) begin
      if (!project_postinc_enabled || InstrM[14:12] > 6 ||
          (InstrM[11:7] != 0 && InstrM[11:7] == InstrM[19:15]))
        $fatal(1, "Unexpected or illegal committed post-increment load: %h", InstrM);
      project_postload = project_postload + 1;
    end else if (project_custom_active && InstrM[6:0] == 7'h7b) begin
      if (!project_postinc_enabled || InstrM[14:12] > 3)
        $fatal(1, "Unexpected or illegal committed post-increment store: %h", InstrM);
      project_poststore = project_poststore + 1;
    end
  end
end
