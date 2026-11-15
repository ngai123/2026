`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 06/16/2026 10:08:56 AM
// Design Name: 
// Module Name: VGA_TEST
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


module VGA_TEST (
    input wire clk_100mhz,    // Main Nexys clock
    input wire reset_btn,     // CPU Reset button
    input wire sw,
    input wire [7:0] player_score,
    
    // VGA Physical Pins
    output wire [3:0] vga_r,
    output wire [3:0] vga_g,
    output wire [3:0] vga_b,
    output wire vga_hsync,
    output wire vga_vsync,
    output reg [2:0] master_state
);

    // Internal wires to connect the modules
    wire [9:0] vga_x;
    wire [9:0] vga_y;
    wire video_on;
    wire [14:0] rom_address;
    wire [11:0] color_data;
    // ==========================================
    // IMAGE MEMORY INSTANTIATION
    // ==========================================
    
    // Wires to hold the pixel output from each of the three frames
    wire [11:0] color_throw_1;
    wire [11:0] color_throw_2;
    wire [11:0] color_throw_prompt;
    wire [11:0] color_pull_1;
    wire [11:0] color_pull_2;
    wire [11:0] color_pull_3;
    wire [11:0] color_turn_1;
    wire [11:0] color_turn_2;
    wire [11:0] color_turn_3;

    // Load Frame 1 (throw_1.hex)
    IMAGE_ROM #(
        .HEX_FILE("throw_1vga.hex") 
    ) rom_frame_1 (
        .clk(clk_100mhz),
        .address(rom_address),        // The coordinate calculated by your VGA controller
        .color_data(color_throw_1)    // The pixel color comes out here
    );

    // Load Frame 2 (throw_2.hex)
    IMAGE_ROM #(
        .HEX_FILE("throw_vga.hex") 
    ) rom_frame_2 (
        .clk(clk_100mhz),
        .address(rom_address),
        .color_data(color_throw_2)
    );

    // Load Frame 3 (throw_prompt.hex)
    IMAGE_ROM #(
        .HEX_FILE("throw_2vga.hex") 
    ) rom_frame_prompt (
        .clk(clk_100mhz),
        .address(rom_address),
        .color_data(color_throw_prompt)
    );
    
    // Stamp out Copy #4
    IMAGE_ROM #(.HEX_FILE("pull_1vga.hex")) rom_pull_1 (
        .clk(clk_100mhz), .address(rom_address), .color_data(color_pull_1)
    );

    // Stamp out Copy #5
    IMAGE_ROM #(.HEX_FILE("pull_2vga.hex")) rom_pull_2 (
        .clk(clk_100mhz), .address(rom_address), .color_data(color_pull_2)
    );

    // Stamp out Copy #6
    IMAGE_ROM #(.HEX_FILE("pull_3vga.hex")) rom_pull_3 (
        .clk(clk_100mhz), .address(rom_address), .color_data(color_pull_3)
    );
    
    IMAGE_ROM #(.HEX_FILE("turn_1vga.hex")) rom_turn_1 (
        .clk(clk_100mhz), .address(rom_address), .color_data(color_turn_1)
    );
    
    IMAGE_ROM #(.HEX_FILE("turn_2vga.hex")) rom_turn_2 (
        .clk(clk_100mhz), .address(rom_address), .color_data(color_turn_2)
    );
    
    IMAGE_ROM #(.HEX_FILE("turn_3vga.hex")) rom_turn_3 (
        .clk(clk_100mhz), .address(rom_address), .color_data(color_turn_3)
    );

    // 1. Instantiate the VGA Controller
    VGA vga_inst (
        .clk_100mhz(clk_100mhz),
        .reset(~reset_btn),    // Nexys A7 CPU reset is active low
        .hsync(vga_hsync),
        .vsync(vga_vsync),
        .video_on(video_on),
        .x_pos(vga_x),
        .y_pos(vga_y)
    );
// ==========================================
    // 2. SPRITE BOUNDING BOX & POSITIONING
    // ==========================================
    parameter X_OFFSET = 0;  
    parameter Y_OFFSET = 0;  

    // Build the Bounding Box (Fixes the undefined error!)
    wire in_sprite_box = (vga_x >= X_OFFSET && vga_x < (X_OFFSET + 640)) &&
                         (vga_y >= Y_OFFSET && vga_y < (Y_OFFSET + 480));

    // Centered ROM Address Calculation
    assign rom_address = (((vga_y - Y_OFFSET) >> 2) * 160) + ((vga_x - X_OFFSET) >> 2);


// ==========================================
    // 3. MASTER GAME CONTROLLER & TIMERS
    // ==========================================
    
    // --- State & Timer Registers ---
    reg [26:0] second_timer = 0; 
    reg [29:0] state_timer = 0;    
    reg [1:0] animation_state = 0; 

    // --- THE UNIFIED STATE MACHINE ---
    // Rule: ALL changes to master_state MUST happen inside this ONE block!
    always @(posedge clk_100mhz) begin
        
        // 1. GLOBAL RESET PRIORITY
        // If the switch is flipped OFF at any time, instantly reset the entire game
        if (sw == 1'b0) begin
            master_state <= 0;
            second_timer <= 0;
            state_timer <= 0;
            animation_state <= 0;
        end 
        else begin
            // 2. THE GAME PHASES
            case (master_state)
                
                0: begin // STATE 0: MENU WAIT
                    if (sw == 1'b1) begin
                        master_state <= 1; // Start Countdown!
                        second_timer <= 0;
                    end
                end
                
                1, 2, 3, 4: begin // STATES 1-4: THE COUNTDOWN (1 Second per screen)
                    if (second_timer >= 100_000_000 - 1) begin
                        second_timer <= 0;
                        master_state <= master_state + 1; // Move to next screen
                    end else begin
                        second_timer <= second_timer + 1;
                    end
                end
                
                5: begin // STATE 5: GAMEPLAY (8 Seconds per animation)
                    if (state_timer >= 800_000_000 - 1) begin
                        state_timer <= 0;
                        
                        if (animation_state == 2) begin
                            master_state <= 6; // All 3 motions done? Move to Result Screen!
                            animation_state <= 0;
                        end else begin
                            animation_state <= animation_state + 1; // Move to next motion
                        end
                        
                    end else begin
                        state_timer <= state_timer + 1;
                    end
                end
                
                6: begin // STATE 6: RESULT SCREEN
                    // The game just sits here displaying the score. 
                    // To play again, the user flips 'sw' down and back up (handled by Global Reset).
                end
                
                default: master_state <= 0;
            endcase
        end
    end
    // --- The 6 FPS Frame Looper ---
    reg [4:0] refresh_counter = 0;
    reg [3:0] active_frame = 0; 
    reg last_vsync;

    always @(posedge clk_100mhz) begin
        last_vsync <= vga_vsync;
        if (last_vsync == 1'b1 && vga_vsync == 1'b0) begin 
            if (refresh_counter == 9) begin 
                refresh_counter <= 0;
                case (animation_state)
                    0: active_frame <= (active_frame >= 2) ? 0 : active_frame + 1;
                    1: active_frame <= (active_frame < 3 || active_frame >= 5) ? 3 : active_frame + 1;
                    2: active_frame <= (active_frame < 6 || active_frame >= 8) ? 6 : active_frame + 1;
                    default: active_frame <= 0;
                endcase
            end else begin
                refresh_counter <= refresh_counter + 1;
            end
        end
    end

// ==========================================
    // 4. THE MULTIPLEXERS & UI WIRING
    // ==========================================
    wire text_pixel_on;
    wire [11:0] game_color; 
    wire [11:0] final_vga_color;

    // Connect the UI Text Engine
    UI_TEXT_ENGINE ui_layer (
        .vga_x(vga_x),
        .vga_y(vga_y),
        .master_state(master_state),
        .screen_x_offset(X_OFFSET), 
        .screen_y_offset(Y_OFFSET), 
        .player_score(player_score), // Pass the score to the text engine!
        .draw_text_pixel(text_pixel_on)
    );

    // Route the correct character frame
    assign game_color = (active_frame == 0) ? color_throw_1 :
                        (active_frame == 1) ? color_throw_2 :
                        (active_frame == 2) ? color_throw_prompt :
                        (active_frame == 3) ? color_pull_1:
                        (active_frame == 4) ? color_pull_2 :
                        (active_frame == 5) ? color_pull_3:
                        (active_frame == 6) ? color_turn_1:
                        (active_frame == 7) ? color_turn_2:
                        (active_frame == 8) ? color_turn_3: 12'h000;

    // The Master Screen Selector
    assign final_vga_color = 
        (master_state <= 4 && text_pixel_on) ? 12'hFFF : // White Menu/Countdown Text
        (master_state == 6 && text_pixel_on) ? 12'hFF0 : // Yellow Result Text!
        (master_state == 5 && in_sprite_box) ? game_color : // The Character Animations
        12'h000; // Black Background

    assign {vga_r, vga_g, vga_b} = (video_on) ? final_vga_color : 12'h000;
endmodule

