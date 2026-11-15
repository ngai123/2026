`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 06/16/2026 10:14:40 AM
// Design Name: 
// Module Name: UI_TEXT_ENGINE
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


module UI_TEXT_ENGINE (
    input wire [9:0] vga_x,
    input wire [9:0] vga_y,
    input wire [2:0] master_state,
    input wire [9:0] screen_x_offset, 
    input wire [9:0] screen_y_offset, 
    input wire [7:0] player_score, // CHANGED: Widen to 8 bits to hold up to 255
    output wire draw_text_pixel 
);
    // BCD Math for two digits
    wire [3:0] score_tens  = (player_score / 10) % 10;
    wire [3:0] score_ones  = player_score % 10;
    
    wire [9:0] virtual_x = (vga_x >= screen_x_offset) ? (vga_x - screen_x_offset) : 0;
    wire [9:0] virtual_y = (vga_y >= screen_y_offset) ? (vga_y - screen_y_offset) : 0;

    reg [7:0] requested_char;
    reg in_text_box;
    reg [2:0] font_col;
    reg [2:0] font_row;

    always @(*) begin
        requested_char = 8'h00; 
        in_text_box = 1'b0;
        font_col = 0;
        font_row = 0;

        case (master_state)
            0: begin // MENU STATE 
                if (virtual_y >= 180 && virtual_y < 212 && virtual_x >= 128 && virtual_x < 512) begin
                    in_text_box = 1'b1; font_row = (virtual_y - 180) >> 2; font_col = (virtual_x - 128) >> 2;
                    case ((virtual_x - 128) >> 5) 
                        0: requested_char = "P";  1: requested_char = "R"; 2: requested_char = "E";  3: requested_char = "S";
                        4: requested_char = "S";  5: requested_char = " "; 6: requested_char = "B";  7: requested_char = "U";
                        8: requested_char = "T";  9: requested_char = "T"; 10: requested_char = "O"; 11: requested_char = "N";
                    endcase
                end
                else if (virtual_y >= 230 && virtual_y < 262 && virtual_x >= 192 && virtual_x < 448) begin
                    in_text_box = 1'b1; font_row = (virtual_y - 230) >> 2; font_col = (virtual_x - 192) >> 2;
                    case ((virtual_x - 192) >> 5)
                        0: requested_char = "T";  1: requested_char = "O"; 2: requested_char = " ";  3: requested_char = "S";
                        4: requested_char = "T";  5: requested_char = "A"; 6: requested_char = "R";  7: requested_char = "T";
                    endcase
                end
            end
            
            1, 2, 3: begin // NUMBER COUNTDOWNS
                if (virtual_y >= 208 && virtual_y < 272 && virtual_x >= 288 && virtual_x < 352) begin
                    in_text_box = 1'b1; font_row = (virtual_y - 208) >> 3; font_col = (virtual_x - 288) >> 3;
                    if (master_state == 1) requested_char = "3";
                    if (master_state == 2) requested_char = "2";
                    if (master_state == 3) requested_char = "1";
                end
            end
            
            4: begin // "START" 
                if (virtual_y >= 208 && virtual_y < 272 && virtual_x >= 160 && virtual_x < 480) begin
                    in_text_box = 1'b1; font_row = (virtual_y - 208) >> 3; font_col = (virtual_x - 160) >> 3;
                    case ((virtual_x - 160) >> 6) 
                        0: requested_char = "S"; 1: requested_char = "T"; 2: requested_char = "A"; 3: requested_char = "R"; 4: requested_char = "T";  
                    endcase
                end
            end

            6: begin // RESULT SCREEN
                // Line 1: "RESULT" (Massive 8x Scale. Start X: 128, Y: 120)
                if (virtual_y >= 120 && virtual_y < 184 && virtual_x >= 128 && virtual_x < 512) begin
                    in_text_box = 1'b1; font_row = (virtual_y - 120) >> 3; font_col = (virtual_x - 128) >> 3;
                    case ((virtual_x - 128) >> 6)
                        0: requested_char = "R";  1: requested_char = "E"; 2: requested_char = "S";  
                        3: requested_char = "U";  4: requested_char = "L"; 5: requested_char = "T";
                    endcase
                end
                // Line 2: "SCORE: XX" (Smaller 4x Scale. Start X: 192, Y: 240)
                else if (virtual_y >= 240 && virtual_y < 272 && virtual_x >= 192 && virtual_x < 480) begin
                    in_text_box = 1'b1; font_row = (virtual_y - 240) >> 2; font_col = (virtual_x - 192) >> 2;
                    case ((virtual_x - 192) >> 5)
                        0: requested_char = "S";  
                        1: requested_char = "C"; 
                        2: requested_char = "O";  
                        3: requested_char = "R";
                        4: requested_char = "E";  
                        5: requested_char = ":"; 
                        6: requested_char = " ";  
                        // Slot 7: Tens (Blank if score is under 10)
                        7: requested_char = (score_tens == 0) ? " " : (8'h30 + score_tens);
                        // Slot 8: Ones (Always shows)
                        8: requested_char = 8'h30 + score_ones;
                    endcase
                end                
            end
        endcase
    end

    // ==========================================
    // 2. THE ASCII FONT ROM (8x8 Pixels)
    // ==========================================
    reg [7:0] font_row_data;

    always @(*) begin
        case (requested_char)
            "0": case (font_row) 0: font_row_data=8'b01111100; 1: font_row_data=8'b10000010; 2: font_row_data=8'b10010010; 3: font_row_data=8'b10100010; 4: font_row_data=8'b10001010; 5: font_row_data=8'b10000010; 6: font_row_data=8'b01111100; 7: font_row_data=8'b00000000; endcase
            "1": case (font_row) 0: font_row_data=8'b00011000; 1: font_row_data=8'b00111000; 2: font_row_data=8'b01011000; 3: font_row_data=8'b00011000; 4: font_row_data=8'b00011000; 5: font_row_data=8'b00011000; 6: font_row_data=8'b01111110; 7: font_row_data=8'b00000000; endcase
            "2": case (font_row) 0: font_row_data=8'b01111100; 1: font_row_data=8'b10000010; 2: font_row_data=8'b00000100; 3: font_row_data=8'b00011000; 4: font_row_data=8'b00110000; 5: font_row_data=8'b01000000; 6: font_row_data=8'b11111110; 7: font_row_data=8'b00000000; endcase
            "3": case (font_row) 0: font_row_data=8'b01111100; 1: font_row_data=8'b10000010; 2: font_row_data=8'b00000100; 3: font_row_data=8'b00011000; 4: font_row_data=8'b00000100; 5: font_row_data=8'b10000010; 6: font_row_data=8'b01111100; 7: font_row_data=8'b00000000; endcase
            "4": case (font_row) 0: font_row_data=8'b00001000; 1: font_row_data=8'b00011000; 2: font_row_data=8'b00101000; 3: font_row_data=8'b01001000; 4: font_row_data=8'b11111110; 5: font_row_data=8'b00001000; 6: font_row_data=8'b00001000; 7: font_row_data=8'b00000000; endcase
            "5": case (font_row) 0: font_row_data=8'b11111110; 1: font_row_data=8'b10000000; 2: font_row_data=8'b11111100; 3: font_row_data=8'b00000010; 4: font_row_data=8'b00000010; 5: font_row_data=8'b10000010; 6: font_row_data=8'b01111100; 7: font_row_data=8'b00000000; endcase
            "6": case (font_row) 0: font_row_data=8'b01111100; 1: font_row_data=8'b10000000; 2: font_row_data=8'b11111100; 3: font_row_data=8'b10000010; 4: font_row_data=8'b10000010; 5: font_row_data=8'b10000010; 6: font_row_data=8'b01111100; 7: font_row_data=8'b00000000; endcase
            "7": case (font_row) 0: font_row_data=8'b11111110; 1: font_row_data=8'b00000010; 2: font_row_data=8'b00000100; 3: font_row_data=8'b00001000; 4: font_row_data=8'b00010000; 5: font_row_data=8'b00100000; 6: font_row_data=8'b01000000; 7: font_row_data=8'b00000000; endcase
            "8": case (font_row) 0: font_row_data=8'b01111100; 1: font_row_data=8'b10000010; 2: font_row_data=8'b10000010; 3: font_row_data=8'b01111100; 4: font_row_data=8'b10000010; 5: font_row_data=8'b10000010; 6: font_row_data=8'b01111100; 7: font_row_data=8'b00000000; endcase
            "9": case (font_row) 0: font_row_data=8'b01111100; 1: font_row_data=8'b10000010; 2: font_row_data=8'b10000010; 3: font_row_data=8'b01111110; 4: font_row_data=8'b00000010; 5: font_row_data=8'b00000100; 6: font_row_data=8'b01111000; 7: font_row_data=8'b00000000; endcase
            "P": case (font_row) 0: font_row_data=8'b11111100; 1: font_row_data=8'b10000010; 2: font_row_data=8'b10000010; 3: font_row_data=8'b11111100; 4: font_row_data=8'b10000000; 5: font_row_data=8'b10000000; 6: font_row_data=8'b10000000; 7: font_row_data=8'b00000000; endcase
            "R": case (font_row) 0: font_row_data=8'b11111100; 1: font_row_data=8'b10000010; 2: font_row_data=8'b10000010; 3: font_row_data=8'b11111100; 4: font_row_data=8'b10010000; 5: font_row_data=8'b10001000; 6: font_row_data=8'b10000100; 7: font_row_data=8'b00000000; endcase
            "E": case (font_row) 0: font_row_data=8'b11111110; 1: font_row_data=8'b10000000; 2: font_row_data=8'b10000000; 3: font_row_data=8'b11111100; 4: font_row_data=8'b10000000; 5: font_row_data=8'b10000000; 6: font_row_data=8'b11111110; 7: font_row_data=8'b00000000; endcase
            "S": case (font_row) 0: font_row_data=8'b01111100; 1: font_row_data=8'b10000010; 2: font_row_data=8'b01100000; 3: font_row_data=8'b00111100; 4: font_row_data=8'b00000110; 5: font_row_data=8'b10000010; 6: font_row_data=8'b01111100; 7: font_row_data=8'b00000000; endcase
            "B": case (font_row) 0: font_row_data=8'b11111100; 1: font_row_data=8'b10000010; 2: font_row_data=8'b11111100; 3: font_row_data=8'b10000010; 4: font_row_data=8'b10000010; 5: font_row_data=8'b11111100; 6: font_row_data=8'b00000000; 7: font_row_data=8'b00000000; endcase
            "U": case (font_row) 0: font_row_data=8'b10000010; 1: font_row_data=8'b10000010; 2: font_row_data=8'b10000010; 3: font_row_data=8'b10000010; 4: font_row_data=8'b10000010; 5: font_row_data=8'b10000010; 6: font_row_data=8'b01111100; 7: font_row_data=8'b00000000; endcase
            "T": case (font_row) 0: font_row_data=8'b11111110; 1: font_row_data=8'b00010000; 2: font_row_data=8'b00010000; 3: font_row_data=8'b00010000; 4: font_row_data=8'b00010000; 5: font_row_data=8'b00010000; 6: font_row_data=8'b00010000; 7: font_row_data=8'b00000000; endcase
            "O": case (font_row) 0: font_row_data=8'b01111100; 1: font_row_data=8'b10000010; 2: font_row_data=8'b10000010; 3: font_row_data=8'b10000010; 4: font_row_data=8'b10000010; 5: font_row_data=8'b10000010; 6: font_row_data=8'b01111100; 7: font_row_data=8'b00000000; endcase
            "N": case (font_row) 0: font_row_data=8'b10000010; 1: font_row_data=8'b11000010; 2: font_row_data=8'b10100010; 3: font_row_data=8'b10010010; 4: font_row_data=8'b10001010; 5: font_row_data=8'b10000110; 6: font_row_data=8'b10000010; 7: font_row_data=8'b00000000; endcase
            "A": case (font_row) 0: font_row_data=8'b00111000; 1: font_row_data=8'b01000100; 2: font_row_data=8'b10000010; 3: font_row_data=8'b11111110; 4: font_row_data=8'b10000010; 5: font_row_data=8'b10000010; 6: font_row_data=8'b10000010; 7: font_row_data=8'b00000000; endcase
            "L": case (font_row) 0: font_row_data=8'b10000000; 1: font_row_data=8'b10000000; 2: font_row_data=8'b10000000; 3: font_row_data=8'b10000000; 4: font_row_data=8'b10000000; 5: font_row_data=8'b10000000; 6: font_row_data=8'b11111110; 7: font_row_data=8'b00000000; endcase
            "C": case (font_row) 0: font_row_data=8'b01111100; 1: font_row_data=8'b10000010; 2: font_row_data=8'b10000000; 3: font_row_data=8'b10000000; 4: font_row_data=8'b10000000; 5: font_row_data=8'b10000010; 6: font_row_data=8'b01111100; 7: font_row_data=8'b00000000; endcase
            ":": case (font_row) 0: font_row_data=8'b00000000; 1: font_row_data=8'b00011000; 2: font_row_data=8'b00011000; 3: font_row_data=8'b00000000; 4: font_row_data=8'b00011000; 5: font_row_data=8'b00011000; 6: font_row_data=8'b00000000; 7: font_row_data=8'b00000000; endcase
            default: font_row_data = 8'h00; 
        endcase
    end

    wire pixel_is_solid = font_row_data[7 - font_col]; 
    assign draw_text_pixel = (in_text_box && pixel_is_solid);

endmodule
