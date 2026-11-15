`timescale 1ns / 1ps
//==============================================================================
// tb_seg7_control.v  (self-checking)
//
// Testbench for seg7_control.v.
//
// seg7_control multiplexes an 8-digit 7-segment display:
//   AN0 = score ones,  AN1 = score tens,
//   AN6 = timer ones,  AN7 = timer tens,
//   AN2..AN5 = always blank.
// Anodes are ACTIVE-LOW (0 = that digit lit). Segments are ACTIVE-LOW with a
// custom encoding (see seg_to_digit below). dp is held high (off). Each digit
// is held for 100_000 clocks (= 1 ms at 100 MHz); a full 8-digit scan = 8 ms.
//
// WHAT THIS TESTBENCH PROVES
//   1. AUTOMATED (console): self-checking. For several (score, timer) inputs it
//      lets the scanner sweep a full refresh, DECODES the live seg/an outputs
//      back into a digit on every clock, captures what each of the four active
//      anodes actually displayed, and compares against the expected BCD digits.
//      It also confirms AN2..AN5 stay blank and dp stays off. Each mismatch
//      prints [FAIL] and tallies an error; ends with TEST PASSED / FAILED and a
//      nonzero exit on failure (CI-friendly).
//   2. VISUAL (waveform): writes tb_seg7_control.vcd. Add an[7:0], seg[6:0],
//      dp and the captured cap_* regs to watch one anode go low at a time with
//      the matching segment pattern.
//
// NOTE ON SIM SPEED: the real refresh constant (100_000) is kept so timing is
// faithful. One full 8-digit scan is 800_000 clocks = 8 ms sim time; we run a
// few of those, so total runtime is tens of ms of simulated time (fast in
// Icarus, a second or two of wall-clock).
//==============================================================================

module tb_seg7_control;

    // ---- DUT signals ----
    reg        CLK100MHZ = 1'b0;
    reg  [7:0] final_marks = 8'd0;
    reg  [3:0] timer_sec   = 4'd0;
    wire [6:0] seg;
    wire       dp;
    wire [7:0] an;

    integer errors = 0;

    // 100 MHz clock
    always #5 CLK100MHZ = ~CLK100MHZ;

    seg7_control dut (
        .CLK100MHZ(CLK100MHZ),
        .final_marks(final_marks),
        .timer_sec(timer_sec),
        .seg(seg),
        .dp(dp),
        .an(an)
    );

    // ---- waveform dump ----
    initial begin
        $dumpfile("tb_seg7_control.vcd");
        $dumpvars(0, tb_seg7_control);
    end

    // ---- segment-pattern -> digit decoder (mirror of the DUT's encoding) ----
    // Returns 0-9 for a known glyph, or 4'hF for blank/unknown.
    function [3:0] seg_to_digit;
        input [6:0] s;
        begin
            case (s)
                7'b000_0001: seg_to_digit = 4'd0;
                7'b100_1111: seg_to_digit = 4'd1;
                7'b001_0010: seg_to_digit = 4'd2;
                7'b000_0110: seg_to_digit = 4'd3;
                7'b100_1100: seg_to_digit = 4'd4;
                7'b010_0100: seg_to_digit = 4'd5;
                7'b010_0000: seg_to_digit = 4'd6;
                7'b000_1111: seg_to_digit = 4'd7;
                7'b000_0000: seg_to_digit = 4'd8;
                7'b000_0100: seg_to_digit = 4'd9;
                default:     seg_to_digit = 4'hF;   // blank / unknown
            endcase
        end
    endfunction

    // ---- live capture of what each active anode is showing ----
    // On every clock, exactly one (or zero) anode is low. Record the decoded
    // digit for the four positions we care about. Also flag any time one of the
    // "always blank" anodes (AN2-5) is driven low, or dp goes low.
    reg [3:0] cap_score_ones, cap_score_tens, cap_timer_ones, cap_timer_tens;
    reg       seen_an0, seen_an1, seen_an6, seen_an7;
    reg       blank_violation, dp_violation;

    task reset_capture;
        begin
            cap_score_ones = 4'hF; cap_score_tens = 4'hF;
            cap_timer_ones = 4'hF; cap_timer_tens = 4'hF;
            seen_an0 = 0; seen_an1 = 0; seen_an6 = 0; seen_an7 = 0;
            blank_violation = 0; dp_violation = 0;
        end
    endtask

    always @(posedge CLK100MHZ) begin
        // dp must stay off (high) at all times
        if (dp !== 1'b1) dp_violation = 1'b1;
        // AN2..AN5 must never be driven low (active)
        if (an[2]===1'b0 || an[3]===1'b0 || an[4]===1'b0 || an[5]===1'b0)
            blank_violation = 1'b1;
        // capture active digit per position (active-low anodes)
        case (an)
            8'b1111_1110: begin cap_score_ones = seg_to_digit(seg); seen_an0 = 1; end
            8'b1111_1101: begin cap_score_tens = seg_to_digit(seg); seen_an1 = 1; end
            8'b1011_1111: begin cap_timer_ones = seg_to_digit(seg); seen_an6 = 1; end
            8'b0111_1111: begin cap_timer_tens = seg_to_digit(seg); seen_an7 = 1; end
            default: ; // all-off or blank position; ignore
        endcase
    end

    // ---- check helper ----
    task check_eq;
        input [31:0] actual;
        input [31:0] expected;
        input [255:0] label;
        begin
            if (actual === expected)
                $display(" [PASS] %0s : got %0d (expected %0d)", label, actual, expected);
            else begin
                $display(" [FAIL] %0s : got %0d (expected %0d)", label, actual, expected);
                errors = errors + 1;
            end
        end
    endtask

    // ---- one full test case: drive inputs, sweep a refresh, check digits ----
    // ONE_DIGIT_MS = 100_000 clocks; a full 8-anode scan = 800_000 clocks.
    // We run ~1.2 scans (1_000_000 clocks = 10 ms) to be sure every active
    // anode is visited at least once.
    task run_case;
        input [7:0] score;
        input [3:0] tmr;
        reg [3:0] exp_so, exp_st, exp_to, exp_tt;
        begin
            final_marks = score;
            timer_sec   = tmr;
            reset_capture;
            // let the scanner sweep at least one full 8 ms refresh
            #(1_000_000 * 10);   // 1,000,000 clocks * 10 ns = 10 ms

            exp_so = score % 10;
            exp_st = (score / 10) % 10;
            exp_to = tmr % 10;
            exp_tt = tmr / 10;

            $display("--- case: score=%0d timer=%0d ---", score, tmr);
            check_eq(seen_an0, 1'b1, "AN0 was scanned");
            check_eq(seen_an1, 1'b1, "AN1 was scanned");
            check_eq(seen_an6, 1'b1, "AN6 was scanned");
            check_eq(seen_an7, 1'b1, "AN7 was scanned");
            check_eq(cap_score_ones, exp_so, "score ones digit (AN0)");
            check_eq(cap_score_tens, exp_st, "score tens digit (AN1)");
            check_eq(cap_timer_ones, exp_to, "timer ones digit (AN6)");
            check_eq(cap_timer_tens, exp_tt, "timer tens digit (AN7)");
            check_eq(blank_violation, 1'b0, "AN2-5 stayed blank");
            check_eq(dp_violation,   1'b0, "dp stayed off (high)");
        end
    endtask

    initial begin
        $display("==========================================================");
        $display(" tb_seg7_control : 7-segment mux display self-check");
        $display(" Layout: AN0=score ones, AN1=score tens,");
        $display("         AN6=timer ones, AN7=timer tens, AN2-5 blank");
        $display("==========================================================");

        run_case(8'd0,  4'd0);   // all zeros
        run_case(8'd4,  4'd8);   // typical mid-game: score 4, 8 s left
        run_case(8'd42, 4'd9);   // two-digit score, timer ones=9
        run_case(8'd99, 4'd0);   // max score 99
        run_case(8'd7,  4'd3);   // single digit each

        $display("----------------------------------------------------------");
        $display(" total errors: %0d", errors);
        $display("----------------------------------------------------------");
        if (errors == 0) begin
            $display(" [PASS] all digits decoded correctly on the mux.");
            $display("==========================================================");
            $display(" TEST PASSED : all checks OK");
            $display("==========================================================");
        end else begin
            $display("==========================================================");
            $display(" TEST FAILED : %0d check(s) failed", errors);
            $display("==========================================================");
        end

        $display(" tb_seg7_control DONE");
        if (errors != 0) $fatal;
        $finish;
    end

endmodule
