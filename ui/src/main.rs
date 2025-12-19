use std::net::SocketAddr;
use std::path::PathBuf;

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Response};
use axum::routing::get;
use axum::Router;
use dioxus::prelude::*;
use dioxus_ssr::render;
use reqwest::Client;
use serde::Deserialize;
use tower_http::services::ServeDir;

#[derive(Clone)]
struct AppState {
    backend_origin: String,
    client: Client,
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
struct FrontpageResponse {
    #[serde(default)]
    orientation: Orientation,
    #[serde(default)]
    city_status: String,
    #[serde(default)]
    alerts: Vec<ApiAlert>,
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
struct Orientation {
    #[serde(default)]
    day: String,
    #[serde(default)]
    date: String,
    #[serde(default)]
    region: String,
    #[serde(default)]
    temp_f: i64,
    #[serde(default)]
    feels_like_f: i64,
    #[serde(default)]
    phrase: String,
    #[serde(default)]
    sunrise: String,
    #[serde(default)]
    sunset: String,
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
struct ApiAlert {
    #[serde(default)]
    severity: String,
    #[serde(default)]
    title: String,
    #[serde(default)]
    body: String,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "mspmetro_ui=info,tower_http=info".into()),
        )
        .init();

    let backend_origin =
        std::env::var("BACKEND_ORIGIN").unwrap_or_else(|_| "http://127.0.0.1:5000".to_string());
    let bind = std::env::var("UI_BIND").unwrap_or_else(|_| "127.0.0.1:8080".to_string());
    let addr: SocketAddr = bind.parse()?;

    let static_dir = pick_static_dir()?;

    let client = Client::builder()
        .user_agent(concat!("mspmetro-ui/", env!("CARGO_PKG_VERSION")))
        .build()?;

    let state = AppState {
        backend_origin,
        client,
    };

    let app = Router::new()
        .route("/healthz", get(|| async { "ok" }))
        .route("/", get(index))
        .nest_service("/static", ServeDir::new(static_dir))
        .with_state(state);

    tracing::info!("UI listening on http://{addr}");
    axum::serve(tokio::net::TcpListener::bind(addr).await?, app).await?;
    Ok(())
}

fn pick_static_dir() -> anyhow::Result<PathBuf> {
    if let Ok(path) = std::env::var("UI_STATIC_DIR") {
        let p = PathBuf::from(path);
        anyhow::ensure!(
            p.is_dir(),
            "UI_STATIC_DIR is set but not a directory: {}",
            p.display()
        );
        return Ok(p);
    }

    let cwd = std::env::current_dir()?;
    let from_cwd = cwd.join("static");
    if from_cwd.is_dir() {
        return Ok(from_cwd);
    }

    let from_source_tree = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../static");
    if from_source_tree.is_dir() {
        return Ok(from_source_tree);
    }

    anyhow::bail!(
        "could not locate static/ directory (set UI_STATIC_DIR or run from repo root)"
    )
}

async fn index(State(state): State<AppState>) -> Response {
    match fetch_frontpage(&state).await {
        Ok(data) => Html(render_document(render_body(data, None))).into_response(),
        Err(err) => {
            tracing::warn!("frontpage fetch failed: {err:#}");
            let msg = format!(
                "Backend not reachable at {}. Start it with `make run-backend` (and Postgres via `make db-up`), or use `make run-static` for the static reference pages.",
                state.backend_origin
            );
            (
                StatusCode::OK,
                Html(render_document(render_body(FrontpageResponse::default(), Some(msg)))),
            )
                .into_response()
        }
    }
}

async fn fetch_frontpage(state: &AppState) -> anyhow::Result<FrontpageResponse> {
    let url = format!("{}/api/v1/frontpage", state.backend_origin.trim_end_matches('/'));
    let resp = state.client.get(url).send().await?.error_for_status()?;
    Ok(resp.json::<FrontpageResponse>().await?)
}

fn render_document(body: String) -> String {
    format!(
        r#"<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="description" content="A calm, accessible daily civic briefing." />

	    <link rel="stylesheet" href="/static/css/daily.css" />
	    <link rel="preload" href="/static/fonts/AtkinsonHyperlegibleNext-Regular.otf" as="font" type="font/otf" crossorigin />
	    <link rel="preload" href="/static/fonts/AtkinsonHyperlegibleNext-Bold.otf" as="font" type="font/otf" crossorigin />
	    <link rel="icon" type="image/png" href="/static/favicon.png" />
	    <link rel="apple-touch-icon" href="/static/favicon.png" />
	    <title>MSPMetro — Daily</title>
	  </head>
  <body id="top">
    {body}
  </body>
</html>
"#
    )
}

fn render_body(data: FrontpageResponse, backend_error: Option<String>) -> String {
    let mut dom = VirtualDom::new_with_props(app, AppProps { data, backend_error });
    dom.rebuild_in_place();
    render(&dom)
}

fn day_full(day: &str) -> &str {
    match day.trim().to_uppercase().as_str() {
        "MON" => "Monday",
        "TUE" => "Tuesday",
        "WED" => "Wednesday",
        "THU" => "Thursday",
        "FRI" => "Friday",
        "SAT" => "Saturday",
        "SUN" => "Sunday",
        _ => day,
    }
}

fn format_date_long(date: &str) -> String {
    let mut parts = date.split('-');
    let year = parts.next();
    let month = parts.next();
    let day = parts.next();

    let (Some(year), Some(month), Some(day)) = (year, month, day) else {
        return date.to_string();
    };

    let month_name = match month {
        "01" | "1" => "January",
        "02" | "2" => "February",
        "03" | "3" => "March",
        "04" | "4" => "April",
        "05" | "5" => "May",
        "06" | "6" => "June",
        "07" | "7" => "July",
        "08" | "8" => "August",
        "09" | "9" => "September",
        "10" => "October",
        "11" => "November",
        "12" => "December",
        _ => return date.to_string(),
    };

    let day = day.trim_start_matches('0');
    format!("{month_name} {day}, {year}")
}

fn region_label(region: &str) -> &str {
    match region.trim() {
        "MINNEAPOLIS–ST. PAUL" | "MINNEAPOLIS-ST. PAUL" => "Twin Cities",
        _ => region,
    }
}

#[derive(Clone, PartialEq, Props)]
struct AppProps {
    data: FrontpageResponse,
    backend_error: Option<String>,
}

fn app(props: AppProps) -> Element {
    let o = &props.data.orientation;

    rsx! {
        a { class: "skip-link", href: "#main", "Skip to main content" }

        header { class: "orientation", aria_label: "Orientation",
            div { class: "wrap",
                dl { class: "orientation-grid",
                    div {
                        dt { "Day" }
                        dd { "{day_full(&o.day)}" }
                    }
                    div {
                        dt { "Date" }
                        dd { "{format_date_long(&o.date)}" }
                    }
                    div {
                        dt { "Region" }
                        dd { "{region_label(&o.region)}" }
                    }
                    div {
                        dt { "Weather" }
                        dd {
                            "{o.temp_f}°F "
                            span { class: "muted", "(feels {o.feels_like_f}°F)" }
                            span { aria_hidden: "true", " \u{2022} " }
                            "{o.phrase}"
                        }
                    }
                    div {
                        dt { "Sunset" }
                        dd { "{o.sunset}" }
                    }
                }
            }
            div { class: "brand",
                img {
                    src: "/static/Logo_SVG.svg",
                    alt: "",
                    aria_hidden: "true",
                    width: "96",
                    height: "96",
                }
            }
        }

        nav { class: "top-nav", aria_label: "Primary",
            div { class: "wrap",
                a { href: "/#weather", "Weather" } " · "
                a { href: "/#metro", "Metro" } " · "
                a { href: "/#world", "World" } " · "
                a { href: "/#neighbors", "Neighbors" } " · "
                a { href: "/#transit", "Transit" } " · "
                a { href: "/#events", "Events" }
            }
        }

        main { id: "main", class: "wrap", tabindex: "-1",
            h1 { class: "sr-only", "MSPMetro Daily Briefing" }

            if let Some(msg) = &props.backend_error {
                section { class: "alerts", aria_label: "Backend status",
                    h2 { class: "kicker", "BACKEND" }
                    p { class: "empty-state", "{msg}" }
                }
            }

            section { class: "status", aria_label: "City status",
                p { class: "status__line",
                    span { class: "status__label", "CITY STATUS:" } " "
                    "{props.data.city_status}"
                }
            }

            section { class: "alerts", aria_live: "polite", aria_atomic: "true",
                h2 { class: "kicker", "ALERTS" }
                if props.data.alerts.is_empty() {
                    p { class: "empty-state", "No current alerts or disruptions" }
                } else {
                    ul { class: "alert-list",
                        for a in props.data.alerts.iter() {
                            li {
                                span { class: "alert-pill", "{a.severity}" }
                                " {a.title}"
                                span { class: "alert-source", "{a.body}" }
                            }
                        }
                    }
                }
            }

            p { class: "what-changed", "" }
        }

        footer { class: "footer", aria_label: "Context",
            div { class: "wrap",
                p { "Daylight: 9h 00m", span { aria_hidden: "true", " • " }, "Moon: Waxing gibbous" }
                p { class: "footer-links",
                    a { href: "/how-we-know/", "How we know" }
                    span { aria_hidden: "true", " · " }
                    a { href: "/daily/", "Daily archive" }
                }
            }
        }
    }
}
