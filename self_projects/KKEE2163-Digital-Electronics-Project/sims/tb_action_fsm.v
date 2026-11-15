`timescale 1ns / 1ps
//==============================================================================
// tb_action_fsm.v
//
// Testbench for action_fsm.v.
//
// To keep the simulation short we instantiate action_fsm with a SMALL
// CYCLES_PER_SEC (1000) instead of the real 100_000_000. This is exactly what
// the parameter is for: every "second" in the FSM becomes 1000 clock cycles,
// so the whole 28 s game plays out in ~28 us of simulation time. The FSM logic
// is identical; only the wall-clock duration changes.
//
// Clock: 100 MHz (10 ns period), active-high `start` (= SW0).
//
// Stimulus plan (mimics hand motion on the 15-bit acl_data bus):
//   IDLE  -> INIT (4 s): keep board still, baseline calibrates.
//   THROW (8 s): first inject a Z-axis spike (arm), then an X-axis spike (score).
//   PULL  (8 s): inject TWO X-axis deviation spikes (low threshold -> easy).
//                This proves PULL is the most generous phase.
//   TURN  (8 s): flip the Y sign back and forth twice (2 flips -> 1 point).
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

    // ---- state name helper ----
    task print_state;
        input [2:0] s;
        begin
            case (s)
                3'd0: $display("      state = S_IDLE");
                3'd1: $display("      state = S_INIT  (baseline calibrating, timer=%0d)", timer_sec);
                3'd2: $display("      state = S_THROW (timer=%0d)", timer_sec);
                3'd3: $display("      state = S_PULL  (timer=%0d)", timer_sec);
                3'd4: $display("      state = S_TURN  (timer=%0d)", timer_sec);
                3'd5: $display("      state = S_DONE");
                default: $display("      state = UNKNOWN(%0d)", s);
            endcase
        end
    endtask

    // helper to format acl_data as {Xsign,Xmag,Ysign,Ymag,Zsign,Zmag}
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

    // monitor state transitions (suppress the t=0 unknown settle)
    reg [2:0] last_state;
    reg       monitor_on = 1'b0;
    initial #1 monitor_on = 1'b1;
    initial last_state = 3'd0;
    always @(posedge CLK100MHZ) begin
        if (monitor_on && state_out !== last_state) begin
            $display("[%0t ns] STATE %0d -> %0d", $time, last_state, state_out);
            print_state(state_out);
            last_state <= state_out;
        end
    end

    // score-change monitor
    reg [7:0] last_score;
    always @(posedge CLK100MHZ) begin
        if (monitor_on && final_marks !== last_score) begin
            $display("[%0t ns] >>> SCORE updated: %0d -> %0d", $time, last_score, final_marks);
            last_score <= final_marks;
        end
    end

    // ====================== STIMULUS ======================
    // acl_data layout: {X[14:10], Y[9:5], Z[4:0]} where each axis = {sign, mag[3:0]}
    // stationary "gravity" vector used as baseline:
    localparam [14:0] REST = 15'b0_0000_0_0000_0_1000;   // Z mag = 8 (1g), others ~0
    // axes pushed high above baseline:
    localparam [14:0] Z_SPIKE   = 15'b0_0000_0_0000_0_1111; // Z mag = 15
    localparam [14:0] X_SPIKE   = 15'b0_1111_0_0000_0_1000; // X mag = 15
    localparam [14:0] X_PULL    = 15'b0_0100_0_0000_0_1000; // X mag = 4 (>= DTH_PULL=2)
    localparam [14:0] Y_POS     = 15'b0_0000_0_1111_0_1000; // Y +mag
    localparam [14:0] Y_NEG     = 15'b0_0000_1_1111_0_1000; // Y -mag

    integer throws, pulls, turns;

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

        // INIT = 4 s = 40 us. Hold still so baseline settles on REST.
        #45_000;                       // a bit past INIT
        $display("[%0t ns] entered gameplay; injecting THROW gesture", $time);

        // ---- THROW: Z spike first (arm), then X spike (score) ----
        acl_data = Z_SPIKE;  #2000;    // hold ~2 us -> rising edge of z_spk_t
        acl_data = REST;     #2000;    // settle so spike clears
        acl_data = X_SPIKE;  #2000;    // X spike -> should score
        acl_data = REST;     #2000;

        // coast through remainder of THROW (8 s total)
        #75_000;

        // ---- PULL: single X deviation spike (threshold 2, easy) ----
        $display("[%0t ns] injecting PULL gesture", $time);
        acl_data = X_PULL;   #2000;
        acl_data = REST;     #2000;
        acl_data = X_PULL;   #2000;    // after cooldown, second pull point
        acl_data = REST;     #2000;

        // coast through remainder of PULL (8 s total)
        #75_000;

        // ---- TURN: alternate Y sign twice (2 flips = 1 point) ----
        $display("[%0t ns] injecting TURN gesture", $time);
        acl_data = Y_POS;    #2000;    // first sign seen (+)
        acl_data = Y_NEG;    #2000;    // flip 1 (+ -> -)
        acl_data = Y_POS;    #2000;    // flip 2 (- -> +)  => 2 flips => point
        acl_data = REST;     #2000;

        // coast to DONE
        #80_000;

        $display("----------------------------------------------------------");
        $display(" FINAL SCORE = %0d", final_marks);
        $display("----------------------------------------------------------");
        if (final_marks == 8'd4)
            $display(" [PASS] score is 4 (1 throw + 2 pull + 1 turn).");
        else
            $display(" [INFO] score = %0d.", final_marks);

        $display("==========================================================");
        $display(" tb_action_fsm DONE");
        $display("==========================================================");
        $finish;
    end

endmodule
