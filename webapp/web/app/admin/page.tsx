import AdminPanel from '@/components/AdminPanel';

export const metadata = { title: 'مدیریت — CARO' };

/* Deliberately not linked from the site navigation. It is not a secret — the
   token is what protects the data, and an unlisted URL protects nothing — but
   a public nav link to an admin screen invites the wrong kind of attention for
   no benefit to any visitor. */
export default function AdminPage() {
  return <AdminPanel />;
}
