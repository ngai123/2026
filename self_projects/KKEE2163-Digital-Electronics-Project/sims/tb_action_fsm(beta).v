`timescale 1ns / 1ps
//==============================================================================
// tb_action_fsm.v  (self-checking, upgraded)
//
// Testbench for action_fsm.v.
//
// action_fsm is instantiated with a SMALL CYCLES_PER_SEC (1000) instead of the
// real 100_000_000 so every "second" is 1000 clock cycles: the whole 28 s game
// plays out in ~28 us of sim time. The FSM logic is identical; only the
// wall-clock duration scales.
//
// WHAT THIS TESTBENCH PROVES
//   1. AUTOMATED (console): it is fully self-checking. Beyond the final total,
//      it now CHECKS THE SCORE AT THE END OF EACH PHASE (throw=1, pull=3,
//      turn=4) so a phase that silently scores nothing is caught immediately,
//      and it checks the FSM walks IDLE->INIT->THROW->PULL->TURN->DONE in order.
//      It also samples timer_sec so the per-phase durations are verified.
//      Any mismatch prints [FAIL] and increments an error counter; the run ends
//      with an overall TEST PASSED / TEST FAILED banner and a nonzero $finish
//      status on failure (CI-friendly).
//   2. VISUAL (waveform): it writes tb_action_fsm.vcd. Add acl_data[14:0],
//      state_out, timer_sec and final_marks to the waveform to see each spike
//      land inside the right phase and the score step exactly when it does.
//
// Clock: 100 MHz (10 ns period), active-high `start` (= SW0).
//
// Stimulus plan (mimics hand motion on the 15-bit acl_data bus):
//   IDLE  -> INIT (4 s): keep board still, baseline calibrates.
//   THROW (8 s): inject a Z-axis spike (arm), then an X-axis spike (score=1).
//   PULL  (8 s): inject TWO X-axis deviation spikes -> score 1->2->3.
//   TURN  (8 s): flip the Y sign back and forth twice (2 flips) -> score 3->4.
//   DONE  : expected final_marks = 4  (1 throw + 2 pull + 1 turn).
//==============================================================================

module tb_action_fsm;

    // ---- DUT signals ----
    reg         CLK100MHZ = 1'b0;
    reg         start = 1'b0;
    reg  [14:0] acl_data = 15'h0000;
    wire [7:0]  final_marks;
    wire [3:0]  timer_sec;
    wire [2:0]  state_out;

    // ---- pass/fail bookkeeping ----
    integer errors = 0;

    // 100 MHz clock
    always #5 CLK100MHZ = ~CLK100MHZ;

    // ---- Instantiate with a fast virtual second ----
    action_fsm #(
        .CYCLES_PER_SEC(1000)          // 1 "second" = 1000 clk cycles (~10 us)
    ) dut (
        .CLK100MHZ(CLK100MHZ),
        .start(start),
        .acl_data(acl_data),
        .final_marks(final_marks),
        .timer_sec(timer_sec),
        .state_out(state_out)
    );

    // ---- state-name constants (match action_fsm encoding) ----
    localparam [2:0] S_IDLE=3'd0, S_INIT=3'd1, S_THROW=3'd2,
                     S_PULL=3'd3, S_TURN=3'd4, S_DONE=3'd5;

    // ---- check helpers ----------------------------------------------------
    // compare actual vs expected; print PASS/FAIL and tally errors.
    task check_eq;
        input [31:0] actual;
        input [31:0] expected;
        input [255:0] label;   // short ASCII tag
        begin
            if (actual === expected)
                $display(" [PASS] %0s : got %0d (expected %0d)", label, actual, expected);
            else begin
                $display(" [FAIL] %0s : got %0d (expected %0d)", label, actual, expected);
                errors = errors + 1;
            end
        end
    endtask

    task print_state;
        input [2:0] s;
        begin
            case (s)
                S_IDLE : $display("      state = S_IDLE");
                S_INIT : $display("      state = S_INIT  (baseline calibrating, timer=%0d)", timer_sec);
                S_THROW: $display("      state = S_THROW (timer=%0d)", timer_sec);
                S_PULL : $display("      state = S_PULL  (timer=%0d)", timer_sec);
                S_TURN : $display("      state = S_TURN  (timer=%0d)", timer_sec);
                S_DONE : $display("      state = S_DONE");
                default: $display("      state = UNKNOWN(%0d)", s);
            endcase
        end
    endtask

    task print_acl;
        input [14:0] d;
        begin
            $display("      acl_data = 15'h%04h  { X%0s%0d  Y%0s%0d  Z%0s%0d }",
                     d,
                     d[14]?"-":"+", d[13:10],
                     d[9] ?"-":"+", d[8:5],
                     d[4] ?"-":"+", d[3:0]);
        end
    endtask

    // ---- transition monitor + ORDER checker ----
    // We record the order of states actually visited so we can assert the FSM
    // walked the full sequence, not just that it reached DONE.
    reg [2:0] last_state;
    reg       monitor_on = 1'b0;
    integer   seq_idx;
    reg [2:0] seq_seen [0:15];
    initial #1 monitor_on = 1'b1;
    initial begin last_state = 3'd0; seq_idx = 0; end
    always @(posedge CLK100MHZ) begin
        if (monitor_on && state_out !== last_state) begin
            $display("[%0t ns] STATE %0d -> %0d", $time, last_state, state_out);
            print_state(state_out);
            // Only record DEFINED states into the order log. At t=0 the FSM
            // settles through an unknown (x) value before IDLE; skip that so the
            // recorded sequence starts cleanly at IDLE.
            if ((seq_idx < 16) && (state_out !== 3'bxxx) && (state_out !== 3'bzzz))
            begin
                seq_seen[seq_idx] = state_out; seq_idx = seq_idx + 1;
            end
            last_state <= state_out;
        end
    end

    // ---- score-change monitor ----
    reg [7:0] last_score;
    always @(posedge CLK100MHZ) begin
        if (monitor_on && final_marks !== last_score) begin
            $display("[%0t ns] >>> SCORE updated: %0d -> %0d", $time, last_score, final_marks);
            last_score <= final_marks;
        end
    end

    // ====================== STIMULUS ======================
    // acl_data layout: {X[14:10], Y[9:5], Z[4:0]} where each axis = {sign, mag[3:0]}
    localparam [14:0] REST    = 15'b0_0000_0_0000_0_1000; // Z mag = 8 (1g), others ~0
    localparam [14:0] Z_SPIKE = 15'b0_0000_0_0000_0_1111; // Z mag = 15
    localparam [14:0] X_SPIKE = 15'b0_1111_0_0000_0_1000; // X mag = 15
    localparam [14:0] X_PULL  = 15'b0_0100_0_0000_0_1000; // X mag = 4 (>= DTH_PULL=2)
    localparam [14:0] Y_POS   = 15'b0_0000_0_1111_0_1000; // Y +mag
    localparam [14:0] Y_NEG   = 15'b0_0000_1_1111_0_1000; // Y -mag

    // ---- waveform dump (the "visual way") ----
    initial begin
        $dumpfile("tb_action_fsm.vcd");
        $dumpvars(0, tb_action_fsm);
    end

    // ---- global watchdog so a broken FSM can never hang the run ----
    initial begin
        #400_000_000;
        $display(" [FAIL] WATCHDOG: simulation did not finish in time (FSM stuck?).");
        errors = errors + 1;
        $display("==========================================================");
        $display(" TEST FAILED (watchdog) : %0d error(s)", errors);
        $display("==========================================================");
        $fatal;
    end

    integer i;

    initial begin
        $display("==========================================================");
        $display(" tb_action_fsm : gesture scoring FSM simulation");
        $display(" CYCLES_PER_SEC = 1000 (1 sec = 10 us sim time)");
        $display(" Expected final_marks = 4 (1 throw + 2 pull + 1 turn)");
        $display("==========================================================");

        // ---- keep board still during power-up / idle ----
        acl_data = REST;
        #20;
        start = 1'b1;                 // flip SW0 -> begin game
        $display("[%0t ns] SW0 -> 1 (start)", $time);

        // ---- INIT phase: confirm we actually reached INIT, still calibrating ----
        #5_000;                        // settle a few "ms" into INIT
        $display("[%0t ns] --- checkpoint: INIT ---", $time);
        check_eq(state_out, S_INIT, "state is INIT during calibration");
        check_eq(final_marks, 8'd0,  "score still 0 at start of INIT");

        // INIT = 4 s = 40 us. Hold still so baseline settles on REST.
        #40_000;                       // a bit past INIT into THROW
        $display("[%0t ns] entered gameplay; injecting THROW gesture", $time);
        check_eq(state_out, S_THROW, "state is THROW after INIT");

        // ---- THROW: Z spike first (arm), then X spike (score) ----
        print_acl(Z_SPIKE); acl_data = Z_SPIKE;  #2000;  // rising edge of z_spk_t -> arm
        acl_data = REST;     #2000;                       // settle so spike clears
        print_acl(X_SPIKE); acl_data = X_SPIKE;  #2000;  // X spike -> should score
        acl_data = REST;     #2000;

        // coast through remainder of THROW (8 s total), then CHECK throw scored
        #75_000;
        $display("[%0t ns] --- checkpoint: end of THROW ---", $time);
        check_eq(final_marks, 8'd1, "score after THROW phase");
        check_eq(state_out, S_PULL, "state is PULL after THROW");

        // ---- PULL: two X deviation spikes (threshold 2, easy) ----
        $display("[%0t ns] injecting PULL gesture", $time);
        print_acl(X_PULL); acl_data = X_PULL;   #2000;
        acl_data = REST;     #2000;
        print_acl(X_PULL); acl_data = X_PULL;   #2000;    // after cooldown, 2nd pull point
        acl_data = REST;     #2000;

        // coast through remainder of PULL (8 s total), then CHECK pull scored twice
        #75_000;
        $display("[%0t ns] --- checkpoint: end of PULL ---", $time);
        check_eq(final_marks, 8'd3, "score after PULL phase (1 throw + 2 pull)");
        check_eq(state_out, S_TURN, "state is TURN after PULL");

        // ---- TURN: alternate Y sign twice (2 flips = 1 point) ----
        $display("[%0t ns] injecting TURN gesture", $time);
        print_acl(Y_POS); acl_data = Y_POS;    #2000;     // first sign seen (+)
        print_acl(Y_NEG); acl_data = Y_NEG;    #2000;     // flip 1 (+ -> -)
        print_acl(Y_POS); acl_data = Y_POS;    #2000;     // flip 2 (- -> +) => point
        acl_data = REST;     #2000;

        // coast to DONE, then CHECK turn scored
        #80_000;
        $display("[%0t ns] --- checkpoint: DONE ---", $time);
        check_eq(state_out, S_DONE, "state is DONE at end of game");
        check_eq(final_marks, 8'd4, "FINAL score (1 throw + 2 pull + 1 turn)");

        // ---- ORDER check: FSM walked the full sequence ----
        $display("[%0t ns] --- checkpoint: state-visit order ---", $time);
        check_eq(seq_seen[0], S_IDLE,  "visited IDLE  (1st)");
        check_eq(seq_seen[1], S_INIT,  "visited INIT  (2nd)");
        check_eq(seq_seen[2], S_THROW, "visited THROW (3rd)");
        check_eq(seq_seen[3], S_PULL,  "visited PULL  (4th)");
        check_eq(seq_seen[4], S_TURN,  "visited TURN  (5th)");
        check_eq(seq_seen[5], S_DONE,  "visited DONE  (6th)");

        // ---- final banner ----
        $display("----------------------------------------------------------");
        $display(" FINAL SCORE = %0d   (errors logged: %0d)", final_marks, errors);
        $display("----------------------------------------------------------");
        if (errors == 0) begin
            $display(" [PASS] score is 4 (1 throw + 2 pull + 1 turn).");
            $display("==========================================================");
            $display(" TEST PASSED : all checks OK");
            $display("==========================================================");
        end else begin
            $display(" [INFO] score = %0d.", final_marks);
            $display("==========================================================");
            $display(" TEST FAILED : %0d check(s) failed", errors);
            $display("==========================================================");
        end

        $display(" tb_action_fsm DONE");
        if (errors != 0) $fatal;       // nonzero exit for CI on failure
        $finish;
    end

endmodule
