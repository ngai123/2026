`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 06/15/2026 10:15:42 AM
// Design Name: 
// Module Name: scoring_design
// Project Name: 
// Target Devices: 
// Tool Versions: 
// Description: 
// 
// Dependencies: 
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
//////////////////////////////////////////////////////////////////////////////////


// Instantiate inside your Top Module

`timescale 1ns / 1ps

module scoring_system (
    input CLK100MHZ,             // System clock
    input rst,                   // Reset signal (active high)
    input start_switch,          // Switch to start the game from the menu
    input [14:0] acl_data,       // 15-bit Accelerometer data from spi_master
    
    output reg [2:0] current_state, // Output state so your VGA module knows what to draw!
    output reg [5:0] total_score,   // Max 30 (10 + 10 + 10)
    output reg [1:0] final_rank     // 0: Try Again, 1: Okay, 2: Excellent
);

    // State definitions
    localparam STATE_MENU  = 3'd0;
    localparam STATE_COUNT = 3'd1;  // 4 seconds
    localparam STATE_THROW = 3'd2;  // 8 seconds
    localparam STATE_PULL  = 3'd3;  // 8 seconds
    localparam STATE_TURN  = 3'd4;  // 8 seconds
    localparam STATE_LOAD  = 3'd5;  // 1 tick calculation
    localparam STATE_RESULT= 3'd6;  // Wait for reset

    // Rank definitions
    localparam RANK_TRY_AGAIN = 2'b00;
    localparam RANK_OKAY      = 2'b01;
    localparam RANK_EXCELLENT = 2'b10;

    // Timing constants (100MHz clock)
    localparam TIME_4_SEC = 30'd400_000_000;
    localparam TIME_8_SEC = 30'd800_000_000;

    // Accelerometer Data Extraction
    wire x_sign = acl_data[14];
    wire [3:0] x_mag = acl_data[13:10];
    wire y_sign = acl_data[9];
    wire [3:0] y_mag = acl_data[8:5];
    wire z_sign = acl_data[4];
    wire [3:0] z_mag = acl_data[3:0];

    // Movement Thresholds
    localparam THRESHOLD_TRIGGER = 4'd6; // Force required to score
    localparam THRESHOLD_NEUTRAL = 4'd2; // Force must drop below this to "reload"

    // Action Triggers
    wire act_throw = (y_mag > THRESHOLD_TRIGGER) && (y_sign == 1'b0); // Forward +Y
    wire act_pull  = (y_mag > THRESHOLD_TRIGGER) && (y_sign == 1'b1); // Backward -Y
    wire act_turn  = (x_mag > THRESHOLD_TRIGGER);                     // Lateral X

    // Neutral Triggers (to prevent spamming one long movement)
    wire neutral_y = (y_mag < THRESHOLD_NEUTRAL);
    wire neutral_x = (x_mag < THRESHOLD_NEUTRAL);

    // Internal Registers
    reg [29:0] timer;
    reg action_locked; // Prevents multi-scoring on a single swing
    
    // Individual phase scores
    reg [3:0] score_throw;
    reg [3:0] score_pull;
    reg [3:0] score_turn;

    always @(posedge CLK100MHZ or posedge rst) begin
        if (rst) begin
            current_state <= STATE_MENU;
            timer <= 30'd0;
            total_score <= 6'd0;
            score_throw <= 4'd0;
            score_pull <= 4'd0;
            score_turn <= 4'd0;
            final_rank <= RANK_TRY_AGAIN;
            action_locked <= 1'b0;
        end else begin
            case (current_state)
                
                STATE_MENU: begin
                    timer <= 30'd0;
                    total_score <= 6'd0;
                    score_throw <= 4'd0;
                    score_pull <= 4'd0;
                    score_turn <= 4'd0;
                    action_locked <= 1'b0;
                    
                    if (start_switch) begin
                        current_state <= STATE_COUNT;
                    end
                end

                STATE_COUNT: begin
                    if (timer >= TIME_4_SEC - 1) begin
                        timer <= 30'd0;
                        current_state <= STATE_THROW;
                    end else begin
                        timer <= timer + 1'b1;
                    end
                end

                STATE_THROW: begin
                    if (timer >= TIME_8_SEC - 1) begin
                        timer <= 30'd0;
                        action_locked <= 1'b0;
                        current_state <= STATE_PULL;
                    end else begin
                        timer <= timer + 1'b1;
                        
                        // Scoring logic with anti-spam lock
                        if (act_throw && !action_locked && score_throw < 4'd10) begin
                            score_throw <= score_throw + 1'b1;
                            action_locked <= 1'b1;
                        end else if (neutral_y) begin
                            action_locked <= 1'b0; // User returned to neutral, ready for next swing
                        end
                    end
                end

                STATE_PULL: begin
                    if (timer >= TIME_8_SEC - 1) begin
                        timer <= 30'd0;
                        action_locked <= 1'b0;
                        current_state <= STATE_TURN;
                    end else begin
                        timer <= timer + 1'b1;
                        
                        if (act_pull && !action_locked && score_pull < 4'd10) begin
                            score_pull <= score_pull + 1'b1;
                            action_locked <= 1'b1;
                        end else if (neutral_y) begin
                            action_locked <= 1'b0;
                        end
                    end
                end

                STATE_TURN: begin
                    if (timer >= TIME_8_SEC - 1) begin
                        timer <= 30'd0;
                        action_locked <= 1'b0;
                        current_state <= STATE_LOAD;
                    end else begin
                        timer <= timer + 1'b1;
                        
                        if (act_turn && !action_locked && score_turn < 4'd10) begin
                            score_turn <= score_turn + 1'b1;
                            action_locked <= 1'b1;
                        end else if (neutral_x) begin
                            action_locked <= 1'b0;
                        end
                    end
                end

                STATE_LOAD: begin
                    // Compile total score (Max 30)
                    total_score <= score_throw + score_pull + score_turn;
                    
                    // Division in FPGA logic is expensive and can cause timing errors.
                    // Instead of (score/30)*100, we pre-calculate the thresholds:
                    // 80% of 30 = 24.
                    // 50% of 30 = 15.
                    
                    if ((score_throw + score_pull + score_turn) > 24)
                        final_rank <= RANK_EXCELLENT;
                    else if ((score_throw + score_pull + score_turn) >= 15)
                        final_rank <= RANK_OKAY;
                    else
                        final_rank <= RANK_TRY_AGAIN;
                        
                    current_state <= STATE_RESULT;
                end

                STATE_RESULT: begin
                    // Hold the result on screen indefinitely. 
                    // User must toggle the 'rst' button to return to STATE_MENU.
                end
                
            endcase
        end
    end
endmodule