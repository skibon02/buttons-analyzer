{
  description = "Buttons Analyzer - BPM/UR stats analyzer";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    rust-overlay.url = "github:oxalica/rust-overlay";
  };

  outputs = { self, nixpkgs, flake-utils, rust-overlay, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        overlays = [ (import rust-overlay) ];
        pkgs = import nixpkgs { inherit system overlays; };

        rustToolchain = pkgs.rust-bin.stable.latest.default.override {
          extensions = [ "rust-src" "rust-analyzer" ];
        };

        nativeBuildInputs = with pkgs; [
          rustToolchain
          pkg-config
          makeWrapper
        ];

        buildInputs = with pkgs; [
          # winit (wayland-only)
          wayland
          wayland-protocols
          libxkbcommon

          # cpal / audio
          alsa-lib

          # python for gui.py
          (python3.withPackages (ps: with ps; [
            pandas
            matplotlib
          ]))
        ];

        LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath buildInputs;
      in
      {
        devShells.default = pkgs.mkShell {
          inherit nativeBuildInputs buildInputs;

          shellHook = ''
            export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:$LD_LIBRARY_PATH
            export WINIT_UNIX_BACKEND=wayland
            echo "Buttons Analyzer dev shell ready!"
            echo "  cargo build -r   -- build the Rust analyzer"
            echo "  python3 gui.py   -- launch the web GUI"
          '';

          RUST_SRC_PATH = "${rustToolchain}/lib/rustlib/src/rust/library";
        };
      }
    );
}
