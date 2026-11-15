`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 06/16/2026 10:21:13 AM
// Design Name: 
// Module Name: VGA
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


module VGA (
    input wire clk_100mhz,  // 100 MHz clock from Nexys A7
    input wire reset,       // System reset
    
    output wire hsync,      // Horizontal sync pulse for monitor
    output wire vsync,      // Vertical sync pulse for monitor
    output wire video_on,   // High when inside the 640x480 active display area
    output wire [9:0] x_pos, // Current pixel X coordinate (0-639)
    output wire [9:0] y_pos  // Current pixel Y coordinate (0-479)
);

    // ==========================================
    // 1. CLOCK DIVIDER (100 MHz -> 25 MHz)
    // ==========================================
    reg [1:0] clk_div;
    wire pixel_tick;

    always @(posedge clk_100mhz or posedge reset) begin
        if (reset) begin
            clk_div <= 0;
        end else begin
            clk_div <= clk_div + 1;
        end
    end
    
    // Pulses high once every 4 clock cycles (25 MHz)
    assign pixel_tick = (clk_div == 2'b00);

    // ==========================================
    // 2. VGA TIMING PARAMETERS (640x480 @ 60Hz)
    // ==========================================
    // Horizontal Timing (Pixels)
    localparam H_DISPLAY       = 640; 
    localparam H_FRONT_PORCH   = 16;
    localparam H_SYNC_PULSE    = 96;
    localparam H_BACK_PORCH    = 48;
    localparam H_TOTAL         = 800; // 640 + 16 + 96 + 48

    // Vertical Timing (Lines)
    localparam V_DISPLAY       = 480; 
    localparam V_FRONT_PORCH   = 10;
    localparam V_SYNC_PULSE    = 2;
    localparam V_BACK_PORCH    = 33;
    localparam V_TOTAL         = 525; // 480 + 10 + 2 + 33

    // ==========================================
    // 3. PIXEL COUNTERS
    // ==========================================
    reg [9:0] h_count = 0;
    reg [9:0] v_count = 0;

    always @(posedge clk_100mhz or posedge reset) begin
        if (reset) begin
            h_count <= 0;
            v_count <= 0;
        end 
        else if (pixel_tick) begin
            if (h_count == (H_TOTAL - 1)) begin
                h_count <= 0;
                // Increment vertical counter when horizontal finishes a line
                if (v_count == (V_TOTAL - 1)) begin
                    v_count <= 0;
                end else begin
                    v_count <= v_count + 1;
                end
            end else begin
                h_count <= h_count + 1;
            end
        end
    end

    // ==========================================
    // 4. OUTPUT ASSIGNMENTS
    // ==========================================
    
    // Generate Sync Pulses (Active Low for 640x480 standard)
    assign hsync = ~( (h_count >= (H_DISPLAY + H_FRONT_PORCH)) && 
                      (h_count <  (H_DISPLAY + H_FRONT_PORCH + H_SYNC_PULSE)) );
                      
    assign vsync = ~( (v_count >= (V_DISPLAY + V_FRONT_PORCH)) && 
                      (v_count <  (V_DISPLAY + V_FRONT_PORCH + V_SYNC_PULSE)) );

    // Enable video output only during the active 640x480 display area
    assign video_on = (h_count < H_DISPLAY) && (v_count < V_DISPLAY);

    // Output the current pixel coordinates
    assign x_pos = (video_on) ? h_count : 10'd0;
    assign y_pos = (video_on) ? v_count : 10'd0;

endmodule
