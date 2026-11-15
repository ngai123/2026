`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module: action_fsm
// Action-evaluating FSM for ADXL362 accelerometer gestures
// Clock: 100 MHz. acl_data = {X[14:10], Y[9:5], Z[4:0]}, each = {sign, mag[3:0]}
//
// timer_sec -> seconds REMAINING in the current phase (countdown).
//              INIT counts 4..1, THROW/PULL/TURN count 8..1, IDLE/DONE = 0.
//
// SCORING:
//   THROW / PULL now detect MOTION as a deviation from a self-calibrating
//   per-axis BASELINE (not an absolute level), so a stationary board held at
//   any tilt scores nothing. A point needs an actual movement spike.
//     - THROW : a hard Z deviation spike THEN a hard X deviation spike.
//     - PULL  : a moderate X deviation spike (either direction) - easy/sensitive.
//   Edge-detected (one point per spike) + short cooldown debounce.
//   TURN is unchanged (sign-flip based, already motion-driven).
//
//   The 4 s INIT phase doubles as baseline calibration: keep the board roughly
//   still during INIT so the baselines settle to the resting (gravity) level.
//////////////////////////////////////////////////////////////////////////////////

module action_fsm #(
    parameter CYCLES_PER_SEC = 100_000_000
)(
    input              CLK100MHZ,
    input              start,
    input      [14:0]  acl_data,
    output reg [7:0]   final_marks,
    output reg [3:0]   timer_sec,
    output reg [2:0]   state_out
);

    // ---------------- Axis decode (sign-magnitude) ----------------
    wire        x_sign = acl_data[14];
    wire [3:0]  x_mag  = acl_data[13:10];
    wire        y_sign = acl_data[9];
    wire [3:0]  y_mag  = acl_data[8:5];
    wire        z_sign = acl_data[4];
    wire [3:0]  z_mag  = acl_data[3:0];

    // zero-extend magnitudes for baseline math
    wire [5:0]  x_w = {2'b00, x_mag};
    wire [5:0]  z_w = {2'b00, z_mag};

    // ---------------- Motion-deviation thresholds (tuning knobs) ----------------
    // How far above/below baseline counts as a spike (range of mag is 0..15).
    localparam [5:0] DTH_THROW = 6'd5;  // hard spike for throw (raise = harder)
    localparam [5:0] DTH_PULL  = 6'd2;  // light spike for pull (lower = easier)
    localparam [3:0] TH_MOVE   = 4'd4;  // TURN flip gate (unchanged)

    // ---------------- Cooldown debounce after each point (0.25 s) ----------------
    localparam integer COOLDOWN_CYCLES = CYCLES_PER_SEC / 4;
    reg  [31:0] cooldown;
    wire        cooling = (cooldown != 32'd0);

    // ---------------- Phase lengths (whole seconds) ----------------
    localparam [3:0] INIT_SECS = 4'd4;
    localparam [3:0] ACT_SECS  = 4'd8;

    // ---------------- FSM states ----------------
    localparam [2:0] S_IDLE=3'd0, S_INIT=3'd1, S_THROW=3'd2,
                     S_PULL=3'd3, S_TURN=3'd4, S_DONE=3'd5;
    reg [2:0]  state;

    // ---------------- Second-based timing ----------------
    reg [31:0] sec_cycle;
    reg [3:0]  sec_count;
    wire       sec_tick = (sec_cycle >= CYCLES_PER_SEC - 1);

    // ---------------- Self-calibrating baselines ----------------
    // While IDLE the baseline snaps to the live reading. While active it adapts
    // slowly (one step per BASE_PERIOD) so gravity/orientation is absorbed but a
    // fast gesture deviates from it.
    localparam integer BASE_PERIOD = CYCLES_PER_SEC / 16;
    reg [5:0]  base_x, base_z;
    reg [31:0] base_div;

    // absolute deviation of each axis from its baseline
    wire [5:0] x_dev = (x_w > base_x) ? (x_w - base_x) : (base_x - x_w);
    wire [5:0] z_dev = (z_w > base_z) ? (z_w - base_z) : (base_z - z_w);

    // instantaneous spike flags + 1-cycle-delayed copies (for rising-edge detect)
    wire x_spk_t = (x_dev >= DTH_THROW);
    wire z_spk_t = (z_dev >= DTH_THROW);
    wire x_spk_p = (x_dev >= DTH_PULL);
    reg  x_spk_t_d, z_spk_t_d, x_spk_p_d;
    wire x_rise_t = x_spk_t & ~x_spk_t_d;
    wire z_rise_t = z_spk_t & ~z_spk_t_d;
    wire x_rise_p = x_spk_p & ~x_spk_p_d;

    always @(posedge CLK100MHZ) begin
        // edge memory (always current)
        x_spk_t_d <= x_spk_t;
        z_spk_t_d <= z_spk_t;
        x_spk_p_d <= x_spk_p;
        // baseline tracking
        if (state == S_IDLE) begin
            base_x   <= x_w;        // snap to live reading while idle
            base_z   <= z_w;
            base_div <= 32'd0;
        end else if (base_div >= BASE_PERIOD - 1) begin
            base_div <= 32'd0;
            if (x_w > base_x) base_x <= base_x + 6'd1;
            else if (x_w < base_x) base_x <= base_x - 6'd1;
            if (z_w > base_z) base_z <= base_z + 6'd1;
            else if (z_w < base_z) base_z <= base_z - 6'd1;
        end else base_div <= base_div + 32'd1;
    end

    // ---------------- TURN trackers (unchanged) ----------------
    reg        y_last_sign, z_last_sign, y_seen, z_seen;
    reg [3:0]  turn_flips;

    // ---------------- THROW tracker ----------------
    reg        throw_armed;   // set after a Z spike, awaiting the X spike

    always @(posedge CLK100MHZ) begin
        // J15 = 0 -> hard reset from ANY state: clear score + timer, hold in IDLE.
        // Only J15 = 1 lets the sequence run.
        if (!start) begin
            final_marks <= 8'd0;
            sec_cycle   <= 32'd0;
            sec_count   <= 4'd0;
            cooldown    <= 32'd0;
            throw_armed <= 1'b0;
            turn_flips  <= 4'd0;
            y_seen      <= 1'b0;
            z_seen      <= 1'b0;
            state       <= S_IDLE;
        end else
        case (state)
        S_IDLE: begin
            final_marks <= 8'd0;
            sec_cycle   <= 32'd0;
            sec_count   <= 4'd0;
            cooldown    <= 32'd0;
            throw_armed <= 1'b0;
            turn_flips  <= 4'd0;
            y_seen      <= 1'b0;
            z_seen      <= 1'b0;
            state <= S_INIT;          // start is guaranteed high here
        end

        S_INIT: begin
            // baseline calibrating here; no scoring
            if (sec_tick) begin
                sec_cycle <= 32'd0;
                if (sec_count >= INIT_SECS - 1) begin
                    sec_count <= 4'd0; cooldown <= 32'd0; throw_armed <= 1'b0;
                    state <= S_THROW;
                end else sec_count <= sec_count + 4'd1;
            end else sec_cycle <= sec_cycle + 32'd1;
        end

        // THROW: Z spike (rising edge) arms, then X spike (rising edge) scores
        S_THROW: begin
            if (cooling) begin
                cooldown <= cooldown - 32'd1;
            end else begin
                if (z_rise_t) throw_armed <= 1'b1;
                if (throw_armed && x_rise_t) begin
                    final_marks <= final_marks + 8'd1;
                    throw_armed <= 1'b0;
                    cooldown    <= COOLDOWN_CYCLES - 1;
                end
            end
            if (sec_tick) begin
                sec_cycle <= 32'd0;
                if (sec_count >= ACT_SECS - 1) begin
                    sec_count <= 4'd0; cooldown <= 32'd0; throw_armed <= 1'b0;
                    state <= S_PULL;
                end else sec_count <= sec_count + 4'd1;
            end else sec_cycle <= sec_cycle + 32'd1;
        end

        // PULL: X deviation spike (rising edge, either direction) scores
        S_PULL: begin
            if (cooling) begin
                cooldown <= cooldown - 32'd1;
            end else if (x_rise_p) begin
                final_marks <= final_marks + 8'd1;
                cooldown    <= COOLDOWN_CYCLES - 1;
            end
            if (sec_tick) begin
                sec_cycle <= 32'd0;
                if (sec_count >= ACT_SECS - 1) begin
                    sec_count <= 4'd0; cooldown <= 32'd0;
                    state <= S_TURN;
                end else sec_count <= sec_count + 4'd1;
            end else sec_cycle <= sec_cycle + 32'd1;
        end

        // TURN: every 2 alternating Y/Z sign flips -> point (unchanged logic)
        S_TURN: begin
            if (cooling) begin
                cooldown   <= cooldown - 32'd1;
                turn_flips <= 4'd0; y_seen <= 1'b0; z_seen <= 1'b0;
            end else begin
                if (y_mag >= TH_MOVE) begin
                    if (!y_seen) begin y_seen <= 1'b1; y_last_sign <= y_sign; end
                    else if (y_sign != y_last_sign) begin
                        y_last_sign <= y_sign; turn_flips <= turn_flips + 4'd1;
                    end
                end
                if (z_mag >= TH_MOVE) begin
                    if (!z_seen) begin z_seen <= 1'b1; z_last_sign <= z_sign; end
                    else if (z_sign != z_last_sign) begin
                        z_last_sign <= z_sign; turn_flips <= turn_flips + 4'd1;
                    end
                end
                if (turn_flips >= 4'd2) begin
                    final_marks <= final_marks + 8'd1;
                    turn_flips  <= 4'd0;
                    cooldown    <= COOLDOWN_CYCLES - 1;
                end
            end
            if (sec_tick) begin
                sec_cycle <= 32'd0;
                if (sec_count >= ACT_SECS - 1) begin
                    sec_count <= 4'd0; cooldown <= 32'd0;
                    state <= S_DONE;
                end else sec_count <= sec_count + 4'd1;
            end else sec_cycle <= sec_cycle + 32'd1;
        end

        S_DONE: state <= S_DONE;     // hold final score; J15=0 resets (handled above)

        default: state <= S_IDLE;
        endcase
    end

    // ---------------- Countdown output ----------------
    always @(*) begin
        case (state)
            S_INIT:                  timer_sec = INIT_SECS - sec_count;
            S_THROW, S_PULL, S_TURN: timer_sec = ACT_SECS  - sec_count;
            default:                 timer_sec = 4'd0;
        endcase
    end

    always @(*) state_out = state;

endmodule explain to me line by line 
