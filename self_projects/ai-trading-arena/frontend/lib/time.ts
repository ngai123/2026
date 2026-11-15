// All timestamps are stored/sent in UTC; render them in Malaysia time.
export const TZ = "Asia/Kuala_Lumpur";

// The backend serializes naive UTC datetimes (no trailing "Z"), which JS would
// otherwise parse as LOCAL time. Force UTC interpretation before formatting.
function asUtcDate(iso: string): Date {
  const hasTz = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasTz ? iso : `${iso}Z`);
}

export function fmtTime(iso: string): string {
  return asUtcDate(iso).toLocaleTimeString([], {
    timeZone: TZ,
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtDateTime(iso: string): string {
  return asUtcDate(iso).toLocaleString([], {
    timeZone: TZ,
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtFull(iso: string): string {
  return asUtcDate(iso).toLocaleString([], { timeZone: TZ });
}
