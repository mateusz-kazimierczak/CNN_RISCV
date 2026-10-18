// Host-side simulation support. No added target instructions or synthesizable RTL.
// The upstream monitor uses the same M-stage commit predicate as minstret.
longint unsigned project_cycles = 0, project_retired = 0;
longint unsigned project_entry = 0, project_return = 0, project_expected = 0;
longint unsigned project_start_cycle = 0, project_instructions = 0;
longint unsigned project_limit = 64'd50000000000;
longint unsigned project_progress = 64'd100000000;
longint unsigned project_output = 0, project_output_pointer_pc = 0;
longint unsigned project_pc_w = 0;
logic project_valid_w = 0, project_htif_read_w = 0;
logic project_active = 0, project_completed = 0;
integer project_metrics_file = 0, project_output_file = 0;
string project_metrics_path, project_output_path;
wire project_commit = dut.core.InstrValidM & ~dut.core.StallW & ~dut.core.FlushW;

initial begin
  if (!$value$plusargs("PROJECT_ENTRY=%h", project_entry)) project_entry = 0;
  if (!$value$plusargs("PROJECT_RETURN=%h", project_return)) project_return = 0;
  if (!$value$plusargs("PROJECT_EXPECTED=%d", project_expected)) project_expected = 0;
  if (!$value$plusargs("PROJECT_MAX_CYCLES=%d", project_limit)) project_limit = 64'd50000000000;
  if (!$value$plusargs("PROJECT_OUTPUT=%h", project_output)) project_output = 0;
  if (!$value$plusargs("PROJECT_OUTPUT_POINTER_PC=%h", project_output_pointer_pc)) project_output_pointer_pc = 0;
  if ($value$plusargs("PROJECT_METRICS=%s", project_metrics_path)) begin
    project_metrics_file = $fopen(project_metrics_path, "w");
    if (project_metrics_file == 0) $fatal(1, "Cannot open project metrics file");
  end
  if ($value$plusargs("PROJECT_OUTPUT_FILE=%s", project_output_path)) begin
    project_output_file = $fopen(project_output_path, "wb");
    if (project_output_file == 0) $fatal(1, "Cannot open project output file");
  end
end

// Spike's HTIF host consumes console requests and clears the mailbox. Wally's
// upstream testbench prints them but does not acknowledge polling clients.
// Model immediate host acknowledgement only on loads of the ELF's tohost word.
// These accesses must remain outside the measured invocation. This does not
// modify caches, kernel memory, instruction semantics or the synthesized core.
always @(posedge clk) begin
  // Settle the LSU writeback register before emulating the host response;
  // the integer register file samples on the following falling edge.
  #1;
  if (project_htif_read_w)
    force dut.core.ReadDataW = '0;
  else
    release dut.core.ReadDataW;
end

always @(posedge clk) begin
  if (reset) begin
    project_cycles = 0;
    project_retired = 0;
    project_valid_w <= 0;
    project_htif_read_w <= 0;
  end else begin
    project_cycles = project_cycles + 1;
    if (project_cycles >= project_limit) $fatal(1, "Project cycle limit reached; incomplete run");
    if (dut.core.TrapM && ~dut.core.StallW)
      $fatal(1, "Unexpected trap pc=%h instr=%h", PCM, InstrM);
    if (!dut.core.StallW) begin
      project_pc_w <= PCM;
      project_valid_w <= project_commit;
      project_htif_read_w <= project_commit && tohost_addr != 0 &&
        dut.core.lsu.IEUAdrM == tohost_addr && dut.core.lsu.MemRWM[1];
    end
    // B0's frozen main loads output->data after Invoke. The runner verifies
    // this instruction against the ELF hash; ResultW supplies its actual value.
    if (project_valid_w && !dut.core.StallW && project_output_pointer_pc != 0 &&
        project_pc_w == project_output_pointer_pc)
      project_output = dut.core.ieu.dp.ResultW;
    if (project_commit) begin
      project_retired = project_retired + 1;
      if (project_entry != 0 && PCM == project_entry) begin
        if (project_active || project_completed) $fatal(1, "Repeated invocation entry");
        project_active = 1;
        project_start_cycle = project_cycles;
        $display("PROJECT invocation entry cycle=%0d pc=%h", project_cycles, PCM);
      end
      if (project_active && PCM == project_return) begin
        project_active = 0;
        project_completed = 1;
        if (project_expected != 0 && project_instructions != project_expected)
          $fatal(1, "Retirements disagree: got %0d expected %0d", project_instructions, project_expected);
        $display("PROJECT invocation complete cycles=%0d instructions=%0d", project_cycles-project_start_cycle, project_instructions);
        if (project_metrics_file != 0) begin
          $fdisplay(project_metrics_file, "{\"cycles\":\"%0d\",\"instructions\":\"%0d\",\"scope\":\"invocation M-stage entry commit inclusive to caller return-site commit exclusive\"}", project_cycles-project_start_cycle, project_instructions);
          $fflush(project_metrics_file);
        end
      end else if (project_active) begin
        project_instructions = project_instructions + 1;
        if (dut.core.lsu.IEUAdrM == tohost_addr && |dut.core.lsu.MemRWM)
          $fatal(1, "HTIF access inside measured invocation");
      end
    end
    if (project_cycles % project_progress == 0) begin
      $display("PROJECT progress cycles=%0d retired=%0d invoke=%0d pc=%h", project_cycles, project_retired, project_instructions, PCM);
      $fflush();
    end
    if (CopyRAM && project_output_file != 0 && project_output >= P.UNCORE_RAM_BASE) begin : project_copy_output
      longint unsigned first_word, last_word;
      first_word = project_output >> 3;
      last_word = (project_output + 999) >> 3;
      for (longint unsigned index = first_word; index <= last_word; index++)
        DCacheFlushFSM.ShadowRAM[29'(index)] =
          dut.uncoregen.uncore.ram.ram.memory.ram.RAM[24'(index-(P.UNCORE_RAM_BASE >> 3))];
    end
    if (Validate && project_output_file != 0) begin : project_dump
      longint unsigned address, word_index;
      logic [63:0] word_value;
      if (!project_completed || project_output < P.UNCORE_RAM_BASE ||
          project_output + 1000 > P.UNCORE_RAM_BASE + P.UNCORE_RAM_RANGE + 1)
        $fatal(1, "Missing invocation or invalid output address %h", project_output);
      // Upstream ShadowRAM contains dirty cache lines; ordinary words remain
      // in the uncore RAM. Cache data takes precedence where populated.
      for (int output_byte = 0; output_byte < 1000; output_byte++) begin
        address = project_output + 64'(output_byte);
        word_index = address >> 3;
        word_value = DCacheFlushFSM.ShadowRAM[29'(word_index)];
        $fwrite(project_output_file, "%c", 8'(word_value >> (8*int'(address[2:0]))));
      end
      $fclose(project_output_file);
      project_output_file = 0;
      $display("PROJECT saved 1000 output bytes at %h", project_output);
    end
  end
end
