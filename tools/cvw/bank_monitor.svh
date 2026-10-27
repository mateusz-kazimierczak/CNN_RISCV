// X4-only host counters. Use the same M-stage retirement boundary as the
// ordinary monitor, but an independent active flag to avoid scheduling races.
longint unsigned project_bank_counts[9] = '{default:0};
longint unsigned project_bank_expected[9] = '{default:0};
string project_bank_names[9] = '{"xdwmac8", "xdwset0", "xdwset1", "xdwset2", "xdwset3",
                                "xdwget0", "xdwget1", "xdwget2", "xdwget3"};
logic project_bank_active = 0;
integer project_bank_file = 0;
string project_bank_path;
initial begin
  if (!$test$plusargs("PROJECT_BANK") || !$value$plusargs("PROJECT_BANK_METRICS=%s", project_bank_path))
    $fatal(1, "Missing bank retirement output path");
  for (int index = 0; index < 9; index++)
    if (!$value$plusargs({"PROJECT_EXPECTED_", project_bank_names[index], "=%d"}, project_bank_expected[index]))
      $fatal(1, "Missing expected bank retirement count: %s", project_bank_names[index]);
  project_bank_file = $fopen(project_bank_path, "w");
  if (project_bank_file == 0) $fatal(1, "Cannot open bank retirement output");
end
always @(posedge clk) begin
  if (reset) begin
    project_bank_active = 0;
    for (int index = 0; index < 9; index++) project_bank_counts[index] = 0;
  end else if (project_commit) begin
    if (PCM == project_entry) project_bank_active = 1;
    if (project_bank_active && PCM == project_return) begin
      project_bank_active = 0;
      for (int index = 0; index < 9; index++)
        if (project_bank_counts[index] != project_bank_expected[index])
          $fatal(1, "Bank retirements disagree: %s got %0d expected %0d",
            project_bank_names[index], project_bank_counts[index], project_bank_expected[index]);
      $fwrite(project_bank_file, "{");
      for (int index = 0; index < 9; index++)
        $fwrite(project_bank_file, "\"%s\":\"%0d\"%s", project_bank_names[index], project_bank_counts[index], index == 8 ? "" : ",");
      $fdisplay(project_bank_file, "}");
      $fclose(project_bank_file);
      $display("PROJECT bank complete mac=%0d set0=%0d get0=%0d", project_bank_counts[0], project_bank_counts[1], project_bank_counts[5]);
    end else if (project_bank_active && project_bank_index(InstrM) >= 0)
      project_bank_counts[project_bank_index(InstrM)] = project_bank_counts[project_bank_index(InstrM)] + 1;
  end
end
