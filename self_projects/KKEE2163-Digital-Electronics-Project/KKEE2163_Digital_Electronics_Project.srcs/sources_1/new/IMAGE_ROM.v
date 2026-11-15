`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 06/16/2026 10:20:06 AM
// Design Name: 
// Module Name: IMAGE_ROM
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


module IMAGE_ROM#(
    // This parameter allows you to change the file name when you instantiate the module
    parameter HEX_FILE = "movement.hex" 
)(
    input wire clk,
    input wire [14:0] address,    // 15-bit address covers up to 32,768. We need 19,200.
    output reg [11:0] color_data  // 12-bit VGA color output (R:4, G:4, B:4)
);

    // 1. Declare the memory array
    // 19,200 memory slots (160x120 pixels), each 12 bits wide
    reg [11:0] memory_array [0:19199];

    // 2. Load the hex file into the BRAM during FPGA synthesis
    initial begin
        $readmemh(HEX_FILE, memory_array);
    end

    // 3. Synchronous Memory Read
    // Block RAM requires a clock edge to output data safely
    always @(posedge clk) begin
        color_data <= memory_array[address];
    end
    
endmodule

