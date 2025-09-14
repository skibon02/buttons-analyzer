use std::fs;
use std::sync::{Arc, Mutex};
use log::{error, info, warn};
use ringbuf::consumer::Consumer;
use crate::calc::convert_deltas;
use crate::Shared;

pub fn export_cur_stats(shared: &Arc<Mutex<Shared>>) {
    let guard = shared.lock().unwrap();
    let (s1, s2) = guard.last_presses.as_slices();
    let mut deltas =  s1.to_vec();
    deltas.extend_from_slice(s2);
    drop(guard);

    let deltas = convert_deltas(&deltas);

    if deltas.len() < 20 {
        warn!("Need at least 20 presses to export stats, got {}", deltas.len());
        return;
    }

    let win_sizes = [20, 40, 60, 80, 100, 120, 140, 160, 180, 200,
        250, 300, 350, 400, 450, 500, 600, 700, 800, 900, 1000, 1500, 2000];
    // determine file id
    let id = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
    if let Err(e) = fs::create_dir("samples") {
        if e.kind() != std::io::ErrorKind::AlreadyExists {
            error!("Failed to create samples directory: {}", e);
            return;
        }
    }
    let file_name = format!("samples/best_bpm_ur_{}.csv", id);
    let bpm_writer = csv::Writer::from_path(&file_name);
    let Ok(mut writer) = bpm_writer else {
        error!("Failed to create file: {}", file_name);
        return;
    };

    writer.write_record(&["Window Size", "Type", "BPM", "UR", "ZX"]).unwrap();
    for &win_size in &win_sizes {
        if deltas.len() < win_size {
            continue;
        }
        let win_stats = crate::calc::calc_stats_windows(&deltas, win_size as u64, 1);
        let best_bpm = win_stats.iter().max_by(|a, b| a.bpm.partial_cmp(&b.bpm).unwrap());
        if let Some(best_bpm) = best_bpm {
            writer.write_record(&[win_size.to_string(), "BPM".to_string(), format!("{:.3}", best_bpm.bpm), format!("{:.3}", best_bpm.ur), format!("{:.3}", best_bpm.zx_ratio * 100.0)]).unwrap();
        }
        let best_ur = win_stats.iter().min_by(|a, b| a.ur.partial_cmp(&b.ur).unwrap());
        if let Some(best_ur) = best_ur {
            writer.write_record(&[win_size.to_string(), "UR".to_string(), format!("{:.3}", best_ur.bpm), format!("{:.3}", best_ur.ur), format!("{:.3}", best_ur.zx_ratio * 100.0)]).unwrap();
        }
        
        // Add ZX as a separate metric type
        let best_xz = win_stats.iter().min_by(|a, b| a.zx_ratio.abs().partial_cmp(&b.zx_ratio.abs()).unwrap());
        if let Some(best_xz) = best_xz {
            writer.write_record(&[win_size.to_string(), "ZX".to_string(), format!("{:.3}", best_xz.bpm), format!("{:.3}", best_xz.ur), format!("{:.3}", best_xz.zx_ratio * 100.0)]).unwrap();
        }
    }

    writer.flush().unwrap();
    info!("Exported stats to {}", file_name);
    
    // Экспортируем историю статистик
    export_stats_history(&deltas, id);
}

fn export_stats_history(deltas: &[(u64, bool)], id: u64) {
    if deltas.len() < 8 {
        warn!("Need at least 8 presses to export history, got {}", deltas.len());
        return;
    }

    let file_name = format!("samples/stats_history_{}.csv", id);
    let history_writer = csv::Writer::from_path(&file_name);
    let Ok(mut writer) = history_writer else {
        error!("Failed to create history file: {}", file_name);
        return;
    };

    writer.write_record(&["Press", "Interval_ms", "BPM_avg8", "UR_avg8", "ZX_avg8"]).unwrap();
    
    // Экспортируем сырые интервалы и скользящее среднее на 8 нажатий
    for i in 0..deltas.len() {
        let interval_ms = deltas[i].0;
        
        if i >= 7 {
            // Вычисляем статистики для последних 8 нажатий
            let window = &deltas[i-7..=i];
            let sum: u64 = window.iter().map(|(d, _)| *d).sum();
            let stats = crate::calc::calc_stats(window, sum);
            
            writer.write_record(&[
                (i + 1).to_string(),
                interval_ms.to_string(), 
                format!("{:.3}", stats.bpm),
                format!("{:.3}", stats.ur),
                format!("{:.3}", stats.zx_ratio * 100.0)
            ]).unwrap();
        } else {
            // Для первых 7 нажатий - только сырые интервалы
            writer.write_record(&[
                (i + 1).to_string(),
                interval_ms.to_string(),
                "".to_string(),
                "".to_string(), 
                "".to_string()
            ]).unwrap();
        }
    }

    writer.flush().unwrap();
    info!("Exported stats history to {}", file_name);
}