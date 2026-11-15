`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 06/15/2026 11:53:30 AM
// Design Name: 
// Module Name: seg7_control
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


module seg7_control(
    input            CLK100MHZ,
    input      [7:0] final_marks,   // score  (0-99 displayed)
    input      [3:0] timer_sec,     // seconds remaining (0-9 displayed in ones)
    output reg [6:0] seg,
    output reg       dp,
    output reg [7:0] an
    );

    // -------------------- Binary -> BCD --------------------
    // Constant-divisor division/modulo; synthesizes to small LUT logic.
    wire [3:0] score_tens = (final_marks / 8'd10) % 8'd10;
    wire [3:0] score_ones =  final_marks % 8'd10;
    wire [3:0] timer_tens =  timer_sec  / 4'd10;   // 0 for 0-9
    wire [3:0] timer_ones =  timer_sec  % 4'd10;

    // -------------------- Segment patterns --------------------
    parameter ZERO  = 7'b000_0001;  // 0
    parameter ONE   = 7'b100_1111;  // 1
    parameter TWO   = 7'b001_0010;  // 2
    parameter THREE = 7'b000_0110;  // 3
    parameter FOUR  = 7'b100_1100;  // 4
    parameter FIVE  = 7'b010_0100;  // 5
    parameter SIX   = 7'b010_0000;  // 6
    parameter SEVEN = 7'b000_1111;  // 7
    parameter EIGHT = 7'b000_0000;  // 8
    parameter NINE  = 7'b000_0100;  // 9
    parameter NULL  = 7'b111_1111;  // all OFF

    // -------------------- Refresh / anode scan --------------------
    reg [2:0]  anode_select = 3'b0;     // selects 1 of 8 anodes
    reg [16:0] anode_timer  = 17'b0;    // ~1 ms per digit

    always @(posedge CLK100MHZ) begin   // 1 ms x 8 = 8 ms full refresh
        if (anode_timer == 17'd99_999) begin   // 10 ns x 100,000 = 1 ms
            anode_timer  <= 17'd0;
            anode_select <= anode_select + 3'd1;
        end else
            anode_timer <= anode_timer + 17'd1;
    end

    // -------------------- Anode drive + active digit select --------------------
    reg [3:0] digit;
    always @(*) begin
        an    = 8'b1111_1111;   // default: all displays OFF
        digit = 4'd0;
        case (anode_select)
            3'd0: begin an = 8'b1111_1110; digit = score_ones; end // AN0  score ones
            3'd1: begin an = 8'b1111_1101; digit = score_tens; end // AN1  score tens
            3'd6: begin an = 8'b1011_1111; digit = timer_ones; end // AN6  timer ones
            3'd7: begin an = 8'b0111_1111; digit = timer_tens; end // AN7  timer tens
            default: an = 8'b1111_1111;                            // AN2-5 OFF
        endcase
    end

    // -------------------- Segment decode --------------------
    always @(*) begin
        dp = 1'b1;                  // decimal point OFF
        if (an == 8'b1111_1111)
            seg = NULL;             // blanked digit (middle positions)
        else case (digit)
            4'd0: seg = ZERO;
            4'd1: seg = ONE;
            4'd2: seg = TWO;
            4'd3: seg = THREE;
            4'd4: seg = FOUR;
            4'd5: seg = FIVE;
            4'd6: seg = SIX;
            4'd7: seg = SEVEN;
            4'd8: seg = EIGHT;
            4'd9: seg = NINE;
            default: seg = NULL;
        endcase
    end

endmodule