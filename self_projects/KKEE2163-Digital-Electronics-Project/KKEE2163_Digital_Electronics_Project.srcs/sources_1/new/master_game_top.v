`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 06/16/2026 10:38:06 AM
// Design Name: 
// Module Name: master_game_top
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


module master_game_top(
    input  wire CLK100MHZ,       // 100 MHz clock from Nexys A7
    input  wire reset_btn,       // CPU Reset Button (Active Low)
    input  wire sw,              // Switch 0 to start/reset the game
    
    // Accelerometer SPI Pins
    input  wire ACL_MISO,
    output wire ACL_MOSI,
    output wire ACL_SCLK,
    output wire ACL_CSN,
    
    // LEDs & 7-Segment Display
    output wire [14:0] LED,
    output wire [6:0] SEG,
    output wire DP,
    output wire [7:0] AN,
    
    // VGA Physical Pins
    output wire [3:0] vga_r,
    output wire [3:0] vga_g,
    output wire [3:0] vga_b,
    output wire vga_hsync,
    output wire vga_vsync,
    
    // Audio Pins
    output wire AUD_PWM,
    output wire AUD_SD
);

    // ==========================================
    // INTERNAL WIRES
    // ==========================================
    wire w_4MHz;
    wire [14:0] acl_data;
    
    // FSM Outputs
    wire [7:0] final_marks;
    wire [3:0] timer_sec;
    wire [2:0] fsm_state;
    
    // VGA & Audio mappings
    wire [2:0] vga_master_state;
    wire [3:0] audio_state_mapped;

    // ==========================================
    // 1. CLOCK GENERATION & ACCELEROMETER SPI
    // ==========================================
    
    iclk_gen clock_generation (
        .CLK100MHZ(CLK100MHZ),
        .clk_4MHz(w_4MHz)
    );
    
    spi_master master (
        .iclk(w_4MHz),
        .miso(ACL_MISO),
        .sclk(ACL_SCLK),
        .mosi(ACL_MOSI),
        .cs(ACL_CSN),
        .acl_data(acl_data)
    );

    // Map raw accelerometer data to LEDs for physical debugging
    assign LED[14:10] = acl_data[14:10]; // X data
    assign LED[9:5]   = acl_data[9:5];   // Y data
    assign LED[4:0]   = acl_data[4:0];   // Z data

    // New 7-Segment Controller (Displays Score & Timer)
    seg7_control display_control (
        .CLK100MHZ(CLK100MHZ),
        .final_marks(final_marks),
        .timer_sec(timer_sec),
        .seg(SEG),
        .dp(DP),
        .an(AN)
    );

    // ==========================================
    // 2. SCORING SYSTEM FSM
    // ==========================================
    
    action_fsm #(
        .CYCLES_PER_SEC(100_000_000)
    ) game_brain (
        .CLK100MHZ(CLK100MHZ),
        .start(sw),                 // Switch triggers the game start
        .acl_data(acl_data),
        .final_marks(final_marks),
        .timer_sec(timer_sec),
        .state_out(fsm_state)
    );

    // ==========================================
    // 3. VGA DISPLAY
    // ==========================================
    
    VGA_TEST vga_engine (
        .clk_100mhz(CLK100MHZ),
        .reset_btn(reset_btn),           // VGA_TEST internally inverts this
        .sw(sw),                         // Switch drives VGA states as well
        .player_score(final_marks), // Passing the lower 4-bits of score to the UI Engine
        .vga_r(vga_r),
        .vga_g(vga_g),
        .vga_b(vga_b),
        .vga_hsync(vga_hsync),
        .vga_vsync(vga_vsync),
        .master_state(vga_master_state)
    );

    // ==========================================
    // 4. AUDIO PROCESSOR
    // ==========================================
    
    // The FSM states and the Audio engine states differ slightly in numbering.
    // This securely translates the action_fsm state to the main_game_audio_processor.
    // action_fsm: 0=IDLE, 1=INIT, 2=THROW, 3=PULL, 4=TURN, 5=DONE
    // audio: 1=HOLD, 4=COUNTDOWN, 5=THROW, 6=PULL, 7=TURN, 9=RESULT
    assign audio_state_mapped = (fsm_state == 3'd0) ? 4'd1 :  // HOLD
                                (fsm_state == 3'd1) ? 4'd4 :  // COUNTDOWN
                                (fsm_state == 3'd2) ? 4'd5 :  // THROW
                                (fsm_state == 3'd3) ? 4'd6 :  // PULL
                                (fsm_state == 3'd4) ? 4'd7 :  // TURN
                                (fsm_state == 3'd5) ? 4'd9 :  // SHOW_RESULT
                                4'd1;

    main_game_audio_processor audio_engine (
        .clk(CLK100MHZ),
        .rst(~reset_btn),
        .master_sw(sw),             // Audio uses active-high reset
        .current_game_state(audio_state_mapped),
        .aud_pwm(AUD_PWM),
        .aud_sd(AUD_SD)
    );

endmodule