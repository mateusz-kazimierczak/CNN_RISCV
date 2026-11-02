# Configuration is generated as Tcl data, with no eval of configuration strings.
proc fatal {message} { puts "SYNTH_FATAL: $message"; exit 2 }
if {[catch {
    source scripts/config.tcl
    set_host_options -max_cores 1
    set_app_var alib_library_analysis_path ./cache/alib
    set_svf outputs/mapped.svf
    set_app_var target_library [list $library]
    set_app_var link_library [concat [list *] $target_library]
    set_app_var search_path [concat $include_dirs [get_app_var search_path]]
    if {![file readable $library]} { error "library is not readable: $library" }
    read_db $library
    redirect reports/library.rpt {
        list_libs
        foreach_in_collection lib [get_libs *] { report_lib [get_object_name $lib] }
    }
    # This small flow uses ns throughout; refuse an incompatible library unit.
    set stream [open reports/library.rpt r]
    set units [read $stream]; close $stream
    if {![regexp -nocase {time[^\n]*[:=][ \t]*1(\.0+)?[ ]*ns} $units]} {
        error "library time unit is not verified as 1 ns; inspect library.rpt"
    }
    puts "SYNTH_LIBRARY_CELLS: [sizeof_collection [get_lib_cells */*]]"
    puts "SYNTH_DC_VERSION: [get_app_var sh_product_version]"
    define_design_lib WORK -path ./work
    analyze -format sverilog -define $defines $sources
    if {[llength $parameters]} {
        elaborate $top -parameters [join $parameters ,]
    } else { elaborate $top }
    current_design $top
    if {![link]} { error "link failed: unresolved reference" }
    redirect reports/check_design.rpt { set design_ok [check_design] }
    if {!$design_ok} { error "check_design failed (strict policy)" }
    set boxes [get_cells -hierarchical -quiet -filter "is_black_box == true"]
    foreach_in_collection cell $boxes {
        set ref [get_attribute $cell ref_name]
        if {[lsearch -exact $allowed_blackboxes $ref] < 0} {
            error "unexpected blackbox: $ref"
        }
    }
    set clkport [get_ports $clock_port]
    if {[sizeof_collection $clkport] != 1} { error "clock port must select one port" }
    create_clock -name synth_clk -period $clock_period $clkport
    set_clock_uncertainty $clock_uncertainty [get_clocks synth_clk]
    set data_inputs [remove_from_collection [all_inputs] $clkport]
    if {[sizeof_collection $data_inputs]} {
        set_input_delay $input_delay -clock synth_clk $data_inputs
    }
    set_output_delay $output_delay -clock synth_clk [all_outputs]
    # Reset is timed like other inputs by default. Explicit exceptions belong in SDC.
    if {$reset_port ne "" && [sizeof_collection [get_ports $reset_port]] != 1} {
        error "reset port must select one port"
    }
    foreach constraint $constraints { source $constraint }
    if {[sizeof_collection [all_clocks]] != 1} { error "this flow requires one clock" }
    if {[get_attribute [get_clocks synth_clk] period] != $clock_period} {
        error "constraint file changed the configured clock period"
    }
    redirect reports/check_timing.rpt { check_timing }
    # check_timing reports endpoints with missing clocks or input/output delays.
    set stream [open reports/check_timing.rpt r]
    set timing_check [read $stream]; close $stream
    if {[regexp -nocase {Warning:} $timing_check]} {
        error "check_timing reported missing or inconsistent constraints"
    }
    if {$compile_mode eq "compile_ultra"} { compile_ultra } else { compile }
    if {![link]} { error "post-compile link failed" }
    redirect reports/check_design.rpt { set design_ok [check_design] }
    if {!$design_ok} { error "post-compile check_design failed" }
    redirect reports/check_timing.rpt { check_timing }
    set stream [open reports/check_timing.rpt r]
    set timing_check [read $stream]; close $stream
    if {[regexp -nocase {Warning:} $timing_check]} {
        error "post-compile check_timing reported inconsistent constraints"
    }
    redirect reports/area.rpt { report_area }
    redirect reports/reference.rpt { report_reference -hierarchy }
    redirect reports/timing.rpt { report_timing -delay_type max -max_paths 10 -input_pins -nets }
    redirect reports/qor.rpt { report_qor }
    set paths [get_timing_paths -delay_type max -max_paths 1]
    if {[sizeof_collection $paths] != 1} { error "no constrained max-delay path" }
    set path [index_collection $paths 0]
    set area [get_attribute [current_design] area]
    set leaves [get_cells -hierarchical -filter "is_hierarchical == false"]
    set unmapped [get_cells -hierarchical -quiet -filter "is_unmapped == true"]
    if {[sizeof_collection $unmapped]} { error "unmapped cells remain" }
    set stream [open reports/metrics.tsv w]
    puts $stream "area\t$area"
    puts $stream "cell_count\t[sizeof_collection $leaves]"
    puts $stream "arrival_ns\t[get_attribute $path arrival]"
    puts $stream "required_ns\t[get_attribute $path required]"
    puts $stream "slack_ns\t[get_attribute $path slack]"
    puts $stream "blackbox_count\t[sizeof_collection $boxes]"
    close $stream
    set stream [open reports/cells.tsv w]
    foreach_in_collection cell $leaves { puts $stream [get_attribute $cell ref_name] }
    close $stream
    write -format verilog -hierarchy -output outputs/mapped.v
    write_sdc outputs/mapped.sdc
    set stream [open outputs/flow_complete w]; puts $stream complete; close $stream
} message]} { fatal $message }
exit 0
